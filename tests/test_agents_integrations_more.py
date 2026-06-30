from __future__ import annotations

import json
import os
import sys
from importlib import import_module
from types import ModuleType
from pathlib import Path
from typing import Any

import pytest

from benchmarks import adapters
from mase.executor import ExecutorAgent
from mase.model_interface import (
    ModelInterface,
    _enforce_cloud_model_policy,
    _load_env_file,
    _resolve_relative_path,
    cloud_models_allowed,
    load_memory_settings,
    resolve_config_path,
    resolve_runs_dir,
)
from mase.notetaker_agent import NotetakerAgent
from mase.planner_agent import PlannerAgent


class FakeNotetaker:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []

    def search(self, keywords: list[str], *, full_query: str, limit: int) -> list[dict[str, str]]:
        self.search_calls.append({"keywords": keywords, "full_query": full_query, "limit": limit})
        return [{"content": "User: alpha"}, {"content": "Assistant: beta"}]

    def write(self, **kwargs: Any) -> None:
        self.writes.append(kwargs)

    def fetch_all_chronological(self, limit: int = 200) -> list[dict[str, str]]:
        return [{"content": "old"}, {"content": "new"}]


def test_notetaker_agent_tool_parsing_execution_mirror_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = NotetakerAgent()
    assert agent.get_tool_schemas()[0]["function"]["name"] == "mase2_write_interaction"
    assert agent.select_operation_mode("q", "ctx") == "default"
    assert agent.parse_tool_arguments({"a": 1}) == {"a": 1}
    assert agent.parse_tool_arguments(" ") == {}
    assert agent.parse_tool_arguments('{"a": 1}') == {"a": 1}
    with pytest.raises(ValueError):
        agent.parse_tool_arguments("{bad")
    with pytest.raises(TypeError):
        agent.parse_tool_arguments(3)
    with pytest.raises(ValueError):
        agent.execute_tool("missing", {})

    agent._tool_handlers["mase2_search_memory"] = lambda **kwargs: [{"id": 1, "score": 0.1}]

    class FakeReranker:
        def rerank(self, query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            assert query == "alpha beta"
            return [{**rows[0], "reranked": True}]

    monkeypatch.setattr("mase.hybrid_recall.HybridReranker", FakeReranker)
    monkeypatch.setenv("MASE_HYBRID_RECALL", "1")
    assert agent.execute_tool("mase2_search_memory", {"keywords": ["alpha", "beta"]})[0]["reranked"] is True

    mirrored: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr("mase.notetaker_agent.tri_vault.is_enabled", lambda: True)
    monkeypatch.setattr("mase.notetaker_agent.tri_vault.mirror_write", lambda bucket, key, payload: mirrored.append((bucket, key, payload)))
    monkeypatch.setattr("mase.notetaker_agent.time.time", lambda: 12.345)
    agent._mirror_tool_write("mase2_write_interaction", {"thread_id": "t1", "role": "user"}, {"ok": True})
    agent._mirror_tool_write("mase2_upsert_fact", {"category": "project", "key": "code"}, {"ok": True})
    agent._mirror_tool_write("mase2_correct_and_log", {"thread_id": "t1"}, {"ok": True})
    agent._mirror_tool_write("mase2_supersede_facts", {}, {"ok": True})
    agent._mirror_tool_write("mase2_get_facts", {}, [])
    assert [item[0] for item in mirrored] == ["sessions", "context", "state", "state"]
    assert mirrored[0][1].startswith("t1__12345__user")

    monkeypatch.setattr("mase.notetaker_agent.tri_vault.mirror_write", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk")))
    agent._mirror_tool_write("mase2_upsert_fact", {"category": "project", "key": "code"}, {"ok": True})

    with pytest.raises(RuntimeError):
        NotetakerAgent().chat_with_tools("remember this")

    class FakeMI:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, agent_type: str, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                return {
                    "message": {
                        "content": "initial",
                        "tool_calls": [
                            {"function": {"name": "mase2_upsert_fact", "arguments": '{"category":"project","key":"code","value":"A"}'}}
                        ],
                    }
                }
            assert messages[-1]["role"] == "tool"
            return {"message": {"content": "final"}}

    fake_mi = FakeMI()
    agent = NotetakerAgent(fake_mi)  # type: ignore[arg-type]
    agent._tool_handlers["mase2_upsert_fact"] = lambda **kwargs: {"stored": kwargs["value"]}
    monkeypatch.setattr("mase.notetaker_agent.tri_vault.is_enabled", lambda: False)
    result = agent.chat_with_tools("store code", context="ctx", mode="manual")
    assert result["mode"] == "manual"
    assert result["initial_response"] == "initial"
    assert result["final_response"] == "final"
    assert result["tool_results"][0]["result"] == {"stored": "A"}


def test_planner_and_executor_agent_public_paths() -> None:
    assert PlannerAgent().plan("q", "memory facts").startswith("1.")
    assert PlannerAgent().plan("q", "无相关记忆。") == "直接基于常识回答问题。"

    class PlannerMI:
        def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["mode"] == "task_planning"
            assert "用户问题: q" in kwargs["messages"][0]["content"]
            return {"message": {"content": " plan \n"}}

    assert PlannerAgent(PlannerMI()).plan("q", "memory") == "plan"

    class ExecutorMI:
        def __init__(self, payload: dict[str, Any] | Exception) -> None:
            self.payload = payload

        def chat(self, **kwargs: Any) -> dict[str, Any]:
            if isinstance(self.payload, Exception):
                raise self.payload
            assert kwargs["agent_type"] == "executor"
            assert kwargs["messages"][0]["role"] == "system"
            return self.payload

    assert ExecutorAgent(ExecutorMI({"message": {"content": "answer"}})).execute("q", "memory") == "answer"
    assert "未能返回有效内容" in ExecutorAgent(ExecutorMI({"message": {}})).execute("q", "memory")
    assert "出现异常" in ExecutorAgent(ExecutorMI(RuntimeError("down"))).execute("q", "memory")


def test_langchain_and_llamaindex_memory_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    langchain_chat_memory = ModuleType("langchain.memory.chat_memory")

    class BaseChatMemory:
        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    class HumanMessage:
        def __init__(self, content: str) -> None:
            self.content = content

    class AIMessage:
        def __init__(self, content: str) -> None:
            self.content = content

    langchain_chat_memory.BaseChatMemory = BaseChatMemory  # type: ignore[attr-defined]
    langchain_messages = ModuleType("langchain_core.messages")
    langchain_messages.HumanMessage = HumanMessage  # type: ignore[attr-defined]
    langchain_messages.AIMessage = AIMessage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain", ModuleType("langchain"))
    monkeypatch.setitem(sys.modules, "langchain.memory", ModuleType("langchain.memory"))
    monkeypatch.setitem(sys.modules, "langchain.memory.chat_memory", langchain_chat_memory)
    monkeypatch.setitem(sys.modules, "langchain_core", ModuleType("langchain_core"))
    monkeypatch.setitem(sys.modules, "langchain_core.messages", langchain_messages)
    lc_memory = import_module("integrations.langchain.mase_memory")

    fake = FakeNotetaker()
    monkeypatch.setattr(lc_memory, "get_notetaker", lambda injected=None: injected or fake)
    mem = lc_memory.MASEMemory(notetaker=fake)
    assert mem.memory_variables == ["history"]
    assert mem.load_memory_variables({}) == {"history": []}
    loaded = mem.load_memory_variables({"input": "alpha beta"})["history"]
    assert [message.content for message in loaded] == ["User: alpha", "Assistant: beta"]
    assert fake.search_calls[0] == {"keywords": ["alpha", "beta"], "full_query": "alpha beta", "limit": 8}
    mem.return_messages = False
    assert mem.load_memory_variables({"question": "alpha"})["history"] == "User: alpha\nAssistant: beta"
    mem.save_context({"input": "hello"}, {"response": "world"})
    mem.save_context({}, {})
    assert fake.writes[-1]["user_query"] == "hello"
    mem.clear()
    monkeypatch.setattr(lc_memory, "mase_ask", lambda question: f"ask:{question}")
    assert lc_memory.mase_ask_chain("q") == "ask:q"

    llama_llms = ModuleType("llama_index.core.llms")

    class MessageRole:
        USER = "user"
        ASSISTANT = "assistant"

    class ChatMessage:
        def __init__(self, role: str, content: str) -> None:
            self.role = role
            self.content = content

    class BaseMemory:
        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    llama_llms.ChatMessage = ChatMessage  # type: ignore[attr-defined]
    llama_llms.MessageRole = MessageRole  # type: ignore[attr-defined]
    llama_memory_types = ModuleType("llama_index.core.memory.types")
    llama_memory_types.BaseMemory = BaseMemory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_index", ModuleType("llama_index"))
    monkeypatch.setitem(sys.modules, "llama_index.core", ModuleType("llama_index.core"))
    monkeypatch.setitem(sys.modules, "llama_index.core.llms", llama_llms)
    monkeypatch.setitem(sys.modules, "llama_index.core.memory", ModuleType("llama_index.core.memory"))
    monkeypatch.setitem(sys.modules, "llama_index.core.memory.types", llama_memory_types)
    li_memory = import_module("integrations.llamaindex.mase_memory")

    fake = FakeNotetaker()
    monkeypatch.setattr(li_memory, "get_notetaker", lambda injected=None: injected or fake)
    li_mem = li_memory.MASELlamaMemory(notetaker=fake)
    assert li_memory.MASELlamaMemory.class_name() == "MASELlamaMemory"
    assert li_mem.get() == []
    assert [message.content for message in li_mem.get("alpha beta")] == ["User: alpha", "Assistant: beta"]
    assert [message.content for message in li_mem.get_all()] == ["old", "new"]
    li_mem.put(li_memory.ChatMessage(role=li_memory.MessageRole.USER, content="user msg"))
    li_mem.put(li_memory.ChatMessage(role=li_memory.MessageRole.ASSISTANT, content="assistant msg"))
    li_mem.set([li_memory.ChatMessage(role=li_memory.MessageRole.USER, content="set msg")])
    assert fake.writes[-1]["user_query"] == "set msg"
    li_mem.reset()


def test_mcp_server_tools_use_scope_and_shape_results(monkeypatch: pytest.MonkeyPatch) -> None:
    fastmcp_module = ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self) -> Any:
            return lambda fn: fn

        def run(self) -> None:
            return None

    fastmcp_module.FastMCP = FastMCP  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp", ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    mcp_server = import_module("integrations.mcp_server.server")

    class FakeMemoryService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def remember_event(self, thread_id: str, role: str, content: str, *, scope_filters: dict[str, str]) -> dict[str, str]:
            self.calls.append(("remember", {"thread_id": thread_id, "role": role, "content": content, "scope": scope_filters}))
            return {"result": "log_id=1"}

        def upsert_fact(self, category: str, key: str, value: str, **kwargs: Any) -> dict[str, str]:
            self.calls.append(("upsert", {"category": category, "key": key, "value": value, **kwargs}))
            return {"category": category, "key": key, "value": value}

        def list_facts(self, category: str | None = None, *, scope_filters: dict[str, str]) -> list[dict[str, str]]:
            self.calls.append(("facts", {"category": category, "scope": scope_filters}))
            return [{"category": "project", "entity_key": "code", "entity_value": "A"}]

        def search_memory(self, keywords: list[str], **kwargs: Any) -> list[dict[str, Any]]:
            self.calls.append(("search", {"keywords": keywords, **kwargs}))
            return [{"content": "c", "thread_id": "t", "_source": "memory_log", "source_log_id": 2}]

        def recall_current_state(self, keywords: list[str], **kwargs: Any) -> list[dict[str, Any]]:
            return [{"content": "state", "category": "project", "entity_key": "code", "entity_value": "A"}]

        def recall_timeline(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"thread_id": "t2", "role": "user", "content": "old", "event_timestamp": "2026"}]

        def recall_thread_tail(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"role": "assistant", "content": "tail", "created_at": "now"}]

        def explain_memory_answer(self, query: str, **kwargs: Any) -> dict[str, Any]:
            return {"query": query, "evidence": []}

    fake_service = FakeMemoryService()
    monkeypatch.setattr(mcp_server, "_memory_service", fake_service)
    assert mcp_server._scope_filters("tenant", "", "private") == {"tenant_id": "tenant", "visibility": "private"}
    assert "remembered role=user" in mcp_server.mase_remember(5050, tenant_id="tenant")
    assert fake_service.calls[-1][1]["content"] == "5050"
    assert "fact upserted: project.port = 5050" in mcp_server.mase_upsert_fact("project", "port", 5050, source_log_id=4)
    assert json.loads(mcp_server.mase_get_facts("project"))[0]["entity_value"] == "A"
    assert mcp_server.mase_recall("alpha beta")[0]["thread"] == "t"
    assert mcp_server.mase_recall_current_state("code")[0]["key"] == "code"
    assert mcp_server.mase_recall_timeline(thread_id="t2")[0]["timestamp"] == "2026"
    assert mcp_server.mase_recall_thread_tail("t2")[0]["content"] == "tail"
    assert mcp_server.mase_explain_answer("why") == {"query": "why", "evidence": []}
    monkeypatch.setattr(mcp_server, "mase_ask", lambda question: f"answer:{question}")
    assert mcp_server.mase_ask_tool("q") == "answer:q"
    assert mcp_server.mase_list_threads() == ["t2"]


def test_model_interface_config_paths_memory_settings_and_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.json"
    explicit.write_text("{}", encoding="utf-8")
    assert resolve_config_path(explicit) == explicit.resolve()
    monkeypatch.setenv("MASE_CONFIG_PATH", str(explicit))
    assert resolve_config_path() == explicit.resolve()

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "MASE_CONFIG_PATH=ignored",
                "KEEP_EXISTING=from-file",
                "NEW_VALUE='quoted'",
                "BAD_LINE",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KEEP_EXISTING", "already")
    _load_env_file(env_file)
    assert os.environ["KEEP_EXISTING"] == "already"
    assert os.environ["NEW_VALUE"] == "quoted"
    assert _resolve_relative_path("child/file.txt", tmp_path) == (tmp_path / "child" / "file.txt").resolve()
    assert _resolve_relative_path(explicit, tmp_path) == explicit.resolve()

    monkeypatch.delenv("MASE_RUNS_DIR", raising=False)
    assert resolve_runs_dir() is None
    monkeypatch.setenv("MASE_RUNS_DIR", str(tmp_path / "runs"))
    assert resolve_runs_dir() == (tmp_path / "runs").resolve()

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "env_file": str(env_file),
                "memory": {"json_dir": "memory", "log_dir": "logs", "index_db": "memory/index.db"},
                "models": {
                    "executor": {
                        "provider": "openai",
                        "model_name": "gpt-test",
                        "system_prompt": "base system",
                        "headers": {"A": "base"},
                        "query_params": {"q": "base"},
                        "extra_body": {"b": "base"},
                        "modes": {
                            "parent": {
                                "headers": {"B": "parent"},
                                "query_params": {"q": "parent"},
                                "extra_body": {"c": "parent"},
                                "temperature": 0.2,
                            },
                            "child": {
                                "extends": "parent",
                                "headers": {"C": "child"},
                                "query_params": {"r": "child"},
                                "extra_body": {"d": "child"},
                                "system_prompt": "child system",
                            },
                        },
                    },
                    "router": {"provider": "ollama", "model_name": "router-model"},
                    "planner": {"provider": "llama_cpp", "model_name": "planner-model"},
                    "notetaker": {"provider": "anthropic", "model_name": "claude-test"},
                },
            }
        ),
        encoding="utf-8",
    )
    settings = load_memory_settings(config)
    assert settings["json_dir"] == (tmp_path / "runs" / "memory").resolve()
    assert settings["index_db"] == (tmp_path / "runs" / "memory" / "index.db").resolve()
    assert settings["log_dir"] == (tmp_path / "runs" / "memory" / "logs").resolve()

    assert cloud_models_allowed() is False
    with pytest.raises(RuntimeError):
        _enforce_cloud_model_policy("openai", "executor", None, "gpt")
    _enforce_cloud_model_policy("ollama", "router", None, "qwen")
    monkeypatch.setenv("MASE_ALLOW_CLOUD_MODELS", "yes")
    assert cloud_models_allowed() is True

    class FakeInterface(ModelInterface):
        def __init__(self, config_path: Path) -> None:
            self.seen: list[tuple[str, float, int, list[dict[str, Any]], list[dict[str, Any]] | None]] = []
            super().__init__(config_path)

        def _call_openai(self, *, agent_config: dict[str, Any], model: str, messages: list[dict[str, Any]], temperature: float, max_tokens: int, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            self.seen.append(("openai", temperature, max_tokens, messages, tools))
            return {"message": {"content": "openai"}, "usage": {"total_tokens": 1}}

        def _call_ollama(self, *, agent_config: dict[str, Any], model: str, messages: list[dict[str, Any]], temperature: float, max_tokens: int, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            self.seen.append(("ollama", temperature, max_tokens, messages, tools))
            return {"message": {"content": "ollama"}}

        def _call_anthropic(self, *, agent_config: dict[str, Any], model: str, messages: list[dict[str, Any]], temperature: float, max_tokens: int, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            self.seen.append(("anthropic", temperature, max_tokens, messages, tools))
            return {"message": {"content": "anthropic"}}

        def _call_llama_cpp(self, model: str, messages: list[dict[str, Any]], temperature: float, max_tokens: int) -> dict[str, Any]:
            self.seen.append(("llama_cpp", temperature, max_tokens, messages, None))
            return {"message": {"content": "llama"}}

    interface = FakeInterface(config)
    child = interface.get_effective_agent_config("executor", mode="child")
    assert child["headers"] == {"A": "base", "B": "parent", "C": "child"}
    assert child["query_params"] == {"q": "parent", "r": "child"}
    assert child["extra_body"] == {"b": "base", "c": "parent", "d": "child"}
    assert interface.describe_agent("executor", mode="child")["model_name"] == "gpt-test"
    assert interface.describe_executor_mode("child")["mode"] == "child"
    assert interface.get_system_prompt("executor", mode="child") == "child system"
    assert interface.inject_system_prompt([{"role": "user", "content": "q"}], "sys")[0] == {"role": "system", "content": "sys"}
    assert interface.inject_system_prompt([{"role": "system", "content": "old"}], "sys")[0]["content"] == "sys"
    with pytest.raises(KeyError):
        interface.get_agent_config("missing")

    monkeypatch.setenv("MASE_TEMP_OVERRIDE", "0.9")
    response = interface.chat("executor", [{"role": "user", "content": "q"}], mode="child", tools=[{"type": "function"}])
    assert response["message"]["content"] == "openai"
    assert interface.seen[-1][1] == 0.9
    assert interface.seen[-1][3][0]["content"] == "child system"
    assert interface.get_call_log()[-1]["agent_role"] == "executor"
    interface.reset_call_log()
    assert interface.get_call_log() == []
    assert interface.chat("router", [{"role": "user", "content": "q"}])["message"]["content"] == "ollama"
    assert interface.chat("planner", [{"role": "user", "content": "q"}])["message"]["content"] == "llama"
    assert interface.chat("notetaker", [{"role": "user", "content": "q"}])["message"]["content"] == "anthropic"
    interface.models_config["bad"] = {"provider": "bad", "model_name": "x"}
    with pytest.raises(ValueError):
        interface.chat("bad", [{"role": "user", "content": "q"}])

    class Closable:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    closable = Closable()
    interface._http_clients = {"x": closable}  # type: ignore[assignment]
    interface._close_http_clients()
    assert closable.closed is True
    assert interface._http_clients == {}


def test_benchmark_adapters_parse_all_supported_record_shapes() -> None:
    assert adapters._stringify(None) == ""
    assert adapters._stringify({"a": 1}) == '{"a": 1}'
    assert adapters._parse_history_text("") == []
    session_turns = adapters._parse_history_text(
        "History Chats:Session A:\n[{'role':'user','content':'hello'}, {'role':'assistant','content': {'x': 1}}]\n"
        "Session B:\n{bad"
    )
    assert [(turn.role, turn.content, turn.session_id) for turn in session_turns] == [
        ("user", "hello", "A"),
        ("assistant", '{"x": 1}', "A"),
    ]
    plain_turns = adapters._parse_history_text("用户：你好\n助手：您好")
    assert [turn.role for turn in plain_turns] == ["user", "assistant"]
    naive_turns = adapters._parse_history_text("line1\nline2\nline3")
    assert [turn.role for turn in naive_turns] == ["user", "assistant", "user"]

    haystack = adapters._parse_longmemeval_haystack_sessions(
        {
            "haystack_session_ids": ["s1"],
            "haystack_dates": ["2026/01/01"],
            "haystack_sessions": [[{"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}, {"role": "bad", "content": "x"}], "bad"],
        }
    )
    assert [(turn.role, turn.timestamp, turn.session_id) for turn in haystack] == [
        ("user", "2026/01/01", "s1"),
        ("assistant", "2026/01/01", "s1"),
    ]
    assert adapters._detect_longmemeval_history_shape({"focused_input": "x"}) == "focused_input"
    assert adapters._detect_longmemeval_history_shape({"history": "x"}) == "full_input"
    assert adapters._detect_longmemeval_history_shape({"haystack_sessions": []}) == "empty"

    lme = adapters.adapt_longmemeval_record(
        {
            "custom_id": "case-1",
            "question": "q",
            "answer": "a",
            "focused_input": "User: hello",
            "question_type": "temporal",
        },
        "longmemeval_s",
    )
    assert lme.id == "case-1"
    assert lme.metadata["history_shape"] == "focused_input"
    assert lme.history[0].content == "hello"

    lv = adapters.adapt_lveval_record(
        {
            "dataset": "loogle",
            "length": "16k",
            "question": "q",
            "answers": ["A"],
            "context": "ctx",
            "answer_keywords": "A; B，C",
            "word_blacklist": "bad、worse",
        },
        "lv_eval",
    )
    assert lv.answer_keywords == ["A", "B", "C"]
    assert lv.word_blacklist == ["bad", "worse"]

    lb = adapters.adapt_longbench_v2_record(
        {"_id": "1", "question": "q", "choice_A": "alpha", "choice_B": "beta", "choice_C": "gamma", "choice_D": "delta", "answer": "z"},
        "longbench_v2",
    )
    assert lb.ground_truth == "A"
    assert "A. alpha" in lb.question

    mmlu = adapters.adapt_mmlu_record({"question": "q", "choices": ["x", "y"], "answer": "B"}, "mmlu")
    assert mmlu.options == ["A. x", "B. y"]
    assert mmlu.metadata["correct_option_text"] == "B. y"
    gpqa = adapters.adapt_gpqa_record({"Question": "q", "Correct Answer": "right", "Incorrect Answer 1": "wrong"}, "gpqa")
    assert gpqa.ground_truth == "A"
    gsm = adapters.adapt_gsm8k_record({"question": "q", "answer": "work\n#### 42"}, "gsm8k")
    assert gsm.ground_truth == "42"
    humaneval = adapters.adapt_humaneval_record({"task_id": "t", "prompt": "def add", "canonical_solution": "return 1", "entry_point": "add"}, "humaneval")
    assert humaneval.answer_keywords == ["def add"]
