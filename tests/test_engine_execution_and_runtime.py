from __future__ import annotations

from pathlib import Path
from typing import Any

from mase import engine, engine_execution
from mase.engine_execution import EngineExecutionMixin
from mase.models import PlannerSnapshot


class FakeWorkspace:
    def __init__(self, verifier_action: str = "off") -> None:
        self.verifier_action = verifier_action

    def to_text(self) -> str:
        return f"workspace={self.verifier_action}"

    def to_dict(self) -> dict[str, str]:
        return {"verifier_action": self.verifier_action}


class FakePlanner:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def plan(self, **kwargs: str) -> str:
        self.calls.append(kwargs)
        return "model plan"


class FakeExecutionModel:
    def __init__(self) -> None:
        self.routing: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any] | Exception] = []

    def get_agent_config(self, agent: str) -> dict[str, Any]:
        assert agent == "executor"
        return {"routing": self.routing}

    def describe_agent(self, agent: str, *, mode: str | None = None) -> dict[str, Any]:
        return {"agent": agent, "described_mode": mode}

    def chat(self, agent_type: str, *, messages: list[dict[str, str]], mode: str) -> dict[str, Any]:
        self.calls.append({"agent_type": agent_type, "messages": messages, "mode": mode})
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return {"message": {"content": f"content:{mode}"}}


class ExecutionHarness(EngineExecutionMixin):
    def __init__(self) -> None:
        self.model_interface = FakeExecutionModel()
        self.planner_agent = FakePlanner()
        self.router_agent = type("Router", (), {"decide": lambda self, **kwargs: {"action": "direct_answer"}})()


def test_executor_prompt_and_planner_boundaries(monkeypatch) -> None:
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2024-01-02")

    english = EngineExecutionMixin._executor_prompt(
        "Which relay is active?",
        "Relay fact",
        instruction_package="Use latest fact.",
        draft_answer="Alder-4",
    )
    assert "Fact sheet:\nRelay fact" in english
    assert "QUESTION_DATE:\n2024-01-02" in english
    assert "Draft answer:\nAlder-4" in english

    chinese = EngineExecutionMixin._executor_prompt("当前端口是多少？", "端口事实")
    assert "事实备忘录：\n端口事实" in chinese
    assert "用户问题：\n当前端口是多少？" in chinese

    harness = ExecutionHarness()
    assert harness._should_use_planner("direct_answer", "general", "") is False
    assert harness._should_use_planner("search_memory", "general", "") is True
    assert harness._heuristic_plan("grounded_analysis", "Which relay?", "facts").source == "heuristic"
    assert harness._build_planner_snapshot("direct_answer", "general", "Which relay?", "无相关记忆。").source == "heuristic"

    planner = harness._build_planner_snapshot("search_memory", "grounded_analysis", "Which relay?", "facts")
    assert planner == PlannerSnapshot(text="model plan", source="model")
    assert harness.planner_agent.calls[0]["memory_context"] == "facts"


def test_select_collaboration_mode_and_instruction_package(monkeypatch) -> None:
    harness = ExecutionHarness()

    harness.model_interface.routing = {"default_collaboration_mode": "verify"}
    assert harness._select_collaboration_mode("Which relay?", "facts", "general") == "verify"

    harness.model_interface.routing = {}
    assert harness._select_collaboration_mode("Which relay?", "", "general") == "off"

    monkeypatch.setattr(engine_execution, "is_long_memory", lambda: True)
    monkeypatch.setattr(engine_execution, "lme_qtype_routing_enabled", lambda: True)
    monkeypatch.setattr(engine_execution, "lme_question_type", lambda: "multi-session")
    assert harness._select_collaboration_mode("Which relay?", "facts", "general") == "split"

    monkeypatch.setattr(engine_execution, "is_long_memory", lambda: False)
    monkeypatch.setattr(engine_execution, "build_reasoning_workspace", lambda question, facts: FakeWorkspace("verify"))
    assert harness._select_collaboration_mode("Which relay?", "facts", "general") == "verify"
    package = harness._build_instruction_package("Which relay?", "facts", PlannerSnapshot("plan"))
    assert "Planner:\nplan" in package
    assert "workspace=verify" in package


def test_call_executor_off_verify_split_and_local_fallback(monkeypatch) -> None:
    harness = ExecutionHarness()
    monkeypatch.setattr(engine_execution, "select_executor_mode", lambda question, facts: "grounded")
    monkeypatch.setattr(engine_execution, "verify_mode_for_question", lambda question: "verify-mode")
    monkeypatch.setattr(engine_execution, "generalizer_mode_for_question", lambda question: "generalizer-mode")
    monkeypatch.setattr(
        EngineExecutionMixin,
        "_extract_answer",
        classmethod(lambda cls, mode, content, user_question, fact_sheet="": f"{mode}|{content}"),
    )

    assert harness.call_executor("Which relay?", "facts", collaboration_mode="off") == "grounded|content:grounded"
    assert harness.call_executor("Which relay?", "facts", collaboration_mode="verify") == "verify-mode|content:verify-mode"
    assert harness.call_executor("Which relay?", "facts", collaboration_mode="split") == "generalizer-mode|content:generalizer-mode"

    fallback_harness = ExecutionHarness()
    fallback_harness.model_interface.responses = [
        RuntimeError("llama runner process has terminated status code: 500 ResponseError"),
        {"message": {"content": "fallback answer"}},
    ]
    monkeypatch.setattr(engine_execution, "select_executor_mode", lambda question, facts: "grounded_long_memory_deepreason_english")
    monkeypatch.setattr(engine_execution, "is_long_memory", lambda: True)
    monkeypatch.setattr(engine_execution, "local_only_models_enabled", lambda: True)
    monkeypatch.setattr(engine_execution, "lme_question_type", lambda: "temporal-reasoning")

    assert fallback_harness.call_executor("Which relay?", "facts", collaboration_mode="off") == (
        "grounded_long_memory_english|fallback answer"
    )


class FakeRuntimeModel:
    def __init__(self) -> None:
        self.call_log: list[dict[str, Any]] = []

    def get_call_log(self) -> list[dict[str, Any]]:
        return list(self.call_log)

    def describe_agent(self, agent: str, *, mode: str | None = None) -> dict[str, Any]:
        return {"agent": agent, "mode": mode}


class FakeRuntimeNotetaker:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.write_calls: list[dict[str, Any]] = []

    def search(self, keywords: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        self.search_calls.append({"keywords": keywords, **kwargs})
        return [{"id": 1, "summary": "Relay is Juniper-7"}]

    def write(self, **kwargs: Any) -> None:
        self.write_calls.append(kwargs)

    def fetch_all_chronological(self) -> list[dict[str, Any]]:
        return [{"id": 1, "summary": "Relay is Juniper-7"}]


class FakePlan:
    def __init__(self) -> None:
        self.search_limit = 7
        self.use_multipass = False
        self.classification = type("Classification", (), {"problem_type": "current_state"})()

    def to_search_kwargs(self) -> dict[str, Any]:
        return {"scope_filters": {"problem_type": "current_state"}}

    def to_dict(self) -> dict[str, Any]:
        return {"search_limit": self.search_limit}


def _runtime_system(route_payload: dict[str, Any]) -> engine.MASESystem:
    system = engine.MASESystem.__new__(engine.MASESystem)
    system.model_interface = FakeRuntimeModel()
    system.notetaker_agent = FakeRuntimeNotetaker()
    system._gc_threads = []
    system.call_router = lambda user_question: dict(route_payload)  # type: ignore[method-assign]
    system.call_executor = lambda **kwargs: "Juniper-7"  # type: ignore[method-assign]
    system._build_fact_sheet_with_notetaker = lambda **kwargs: ("facts", "fake_sheet")  # type: ignore[method-assign]
    system._select_collaboration_mode = lambda question, facts, mode: "off"  # type: ignore[method-assign]
    system._build_instruction_package = lambda question, facts, planner: "instructions"  # type: ignore[method-assign]
    system.describe_executor_target = lambda **kwargs: {"mode": kwargs["mode"], "use_memory": kwargs["use_memory"]}  # type: ignore[method-assign]
    return system


def test_run_with_trace_direct_and_search_paths(monkeypatch) -> None:
    monkeypatch.setattr(engine, "select_executor_mode", lambda question, facts: "grounded")
    monkeypatch.setattr(engine, "use_deterministic_fact_sheet", lambda: True)
    monkeypatch.setattr(engine, "build_reasoning_workspace", lambda question, facts: FakeWorkspace("off"))
    monkeypatch.setattr(engine, "build_trace_steps", lambda **kwargs: [{"name": "fake"}])
    monkeypatch.setattr(engine, "record_trace_payload", lambda **kwargs: "trace.jsonl")
    monkeypatch.setattr(engine, "is_long_memory", lambda: False)
    monkeypatch.setattr(engine, "is_long_context_qa", lambda: False)
    monkeypatch.setattr(engine, "is_multidoc_long_context", lambda: False)
    monkeypatch.setattr(engine, "determine_memory_heat", lambda question: "warm")
    monkeypatch.setattr(engine, "build_retrieval_plan", lambda *args, **kwargs: FakePlan())
    monkeypatch.setattr(engine, "multipass_allowed_for_task", lambda: False)
    monkeypatch.setenv("MASE_AUDIT_MARKDOWN", "0")
    monkeypatch.setenv("MASE_GC_AUTO", "0")

    direct = _runtime_system({"action": "direct_answer", "keywords": []})
    direct_trace = engine.MASESystem.run_with_trace(direct, "Which relay?", log=False)
    assert direct_trace.answer == "Juniper-7"
    assert direct_trace.route.action == "direct_answer"
    assert direct_trace.search_results == []
    assert direct_trace.record_path == "trace.jsonl"

    search = _runtime_system({"action": "search_memory", "keywords": ["relay"]})
    search_trace = engine.MASESystem.run_with_trace(search, "Which relay?", log=True)
    assert search_trace.route.action == "search_memory"
    assert search_trace.search_results == [{"id": 1, "summary": "Relay is Juniper-7"}]
    assert search.notetaker_agent.search_calls[0]["limit"] == 7
    assert search.notetaker_agent.write_calls[0]["assistant_response"] == "Juniper-7"


def test_engine_singleton_cache_and_reload(monkeypatch, tmp_path: Path) -> None:
    class FakeSystem:
        def __init__(self, config_path: str | Path | None = None) -> None:
            self.config_path = str(config_path)
            self.reloads = 0

        def reload(self) -> None:
            self.reloads += 1

    monkeypatch.setattr(engine, "MASESystem", FakeSystem)
    monkeypatch.setattr(engine, "resolve_config_path", lambda config_path=None: (tmp_path / str(config_path or "config.json")))
    engine._SYSTEM_CACHE.clear()

    first = engine.get_system("config-a.json")
    second = engine.get_system("config-a.json")
    assert first is second

    reloaded_same = engine.get_system("config-a.json", reload=True)
    assert reloaded_same is first
    assert first.reloads == 1

    replaced = engine.reload_system("config-a.json")
    assert replaced is not first
    assert engine.get_system("config-a.json") is replaced
