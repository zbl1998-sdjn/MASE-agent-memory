"""Smoke test: integration layer can instantiate and route onto the unified backend path.

Stubs optional dependencies (mcp, langchain, llama_index) without polluting
global module state during pytest collection.
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest


def _stub_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    mcp_mod = types.ModuleType("mcp")
    mcp_server = types.ModuleType("mcp.server")
    mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")

    class _FakeMCP:
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self):
            return lambda f: f

        def run(self) -> None:
            pass

    mcp_fastmcp.FastMCP = _FakeMCP
    monkeypatch.setitem(sys.modules, "mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "mcp.server", mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", mcp_fastmcp)


def _stub_langchain(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BaseChatMemory:
        memory_key: str = "history"
        return_messages: bool = True

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                object.__setattr__(self, key, value)

    class _HumanMessage:
        def __init__(self, content: str) -> None:
            self.content = content

    class _AIMessage:
        def __init__(self, content: str) -> None:
            self.content = content

    lc_mod = types.ModuleType("langchain")
    lc_memory = types.ModuleType("langchain.memory")
    lc_chat_memory = types.ModuleType("langchain.memory.chat_memory")
    lc_core = types.ModuleType("langchain_core")
    lc_messages = types.ModuleType("langchain_core.messages")

    lc_chat_memory.BaseChatMemory = _BaseChatMemory
    lc_messages.HumanMessage = _HumanMessage
    lc_messages.AIMessage = _AIMessage

    monkeypatch.setitem(sys.modules, "langchain", lc_mod)
    monkeypatch.setitem(sys.modules, "langchain.memory", lc_memory)
    monkeypatch.setitem(sys.modules, "langchain.memory.chat_memory", lc_chat_memory)
    monkeypatch.setitem(sys.modules, "langchain_core", lc_core)
    monkeypatch.setitem(sys.modules, "langchain_core.messages", lc_messages)


def _stub_llamaindex(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BaseMemory:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                object.__setattr__(self, key, value)

    class _ChatMessage:
        def __init__(self, role: str, content: str) -> None:
            self.role = role
            self.content = content

    class _MessageRole:
        USER = "user"
        ASSISTANT = "assistant"

    li_mod = types.ModuleType("llama_index")
    li_core = types.ModuleType("llama_index.core")
    li_llms = types.ModuleType("llama_index.core.llms")
    li_memory = types.ModuleType("llama_index.core.memory")
    li_memory_types = types.ModuleType("llama_index.core.memory.types")

    li_llms.ChatMessage = _ChatMessage
    li_llms.MessageRole = _MessageRole
    li_memory_types.BaseMemory = _BaseMemory

    monkeypatch.setitem(sys.modules, "llama_index", li_mod)
    monkeypatch.setitem(sys.modules, "llama_index.core", li_core)
    monkeypatch.setitem(sys.modules, "llama_index.core.llms", li_llms)
    monkeypatch.setitem(sys.modules, "llama_index.core.memory", li_memory)
    monkeypatch.setitem(sys.modules, "llama_index.core.memory.types", li_memory_types)


@pytest.fixture()
def integration_modules(monkeypatch: pytest.MonkeyPatch):
    _stub_mcp(monkeypatch)
    _stub_langchain(monkeypatch)
    _stub_llamaindex(monkeypatch)

    for name in (
        "integrations.langchain.mase_memory",
        "integrations.llamaindex.mase_memory",
        "integrations.mcp_server.server",
    ):
        sys.modules.pop(name, None)

    bn_mod = importlib.import_module("mase.benchmark_notetaker")
    lc_mod = importlib.import_module("integrations.langchain.mase_memory")
    li_mod = importlib.import_module("integrations.llamaindex.mase_memory")
    mcp_mod = importlib.import_module("integrations.mcp_server.server")

    yield {
        "BenchmarkNotetaker": bn_mod.BenchmarkNotetaker,
        "get_notetaker": bn_mod.get_notetaker,
        "MASEMemory": lc_mod.MASEMemory,
        "MASELlamaMemory": li_mod.MASELlamaMemory,
        "mcp_mod": mcp_mod,
    }

    for name in (
        "integrations.langchain.mase_memory",
        "integrations.llamaindex.mase_memory",
        "integrations.mcp_server.server",
    ):
        sys.modules.pop(name, None)


def test_get_notetaker_default_returns_benchmark_notetaker(integration_modules):
    nt = integration_modules["get_notetaker"]()
    assert isinstance(nt, integration_modules["BenchmarkNotetaker"])


def test_get_notetaker_injection_returns_same_instance(integration_modules):
    existing = integration_modules["BenchmarkNotetaker"]()
    result = integration_modules["get_notetaker"](existing)
    assert result is existing


def test_get_notetaker_env_override(tmp_path, monkeypatch, integration_modules):
    monkeypatch.setenv("MASE_BACKEND_CONFIG", str(tmp_path / "config.json"))
    nt = integration_modules["get_notetaker"]()
    assert isinstance(nt, integration_modules["BenchmarkNotetaker"])


def test_langchain_no_arg_construction(integration_modules):
    mem = integration_modules["MASEMemory"]()
    assert mem.notetaker is not None
    assert isinstance(mem.notetaker, integration_modules["BenchmarkNotetaker"])


def test_langchain_notetaker_injection(integration_modules):
    nt = integration_modules["BenchmarkNotetaker"]()
    mem = integration_modules["MASEMemory"](notetaker=nt)
    assert mem.notetaker is nt


def test_llamaindex_no_arg_construction(integration_modules):
    mem = integration_modules["MASELlamaMemory"]()
    assert mem.notetaker is not None
    assert isinstance(mem.notetaker, integration_modules["BenchmarkNotetaker"])


def test_llamaindex_notetaker_injection(integration_modules):
    nt = integration_modules["BenchmarkNotetaker"]()
    mem = integration_modules["MASELlamaMemory"](notetaker=nt)
    assert mem.notetaker is nt


def test_mcp_notetaker_is_benchmark_notetaker(integration_modules):
    assert isinstance(
        integration_modules["mcp_mod"]._notetaker,
        integration_modules["BenchmarkNotetaker"],
    )


def test_write_recall_unified_path(tmp_path, monkeypatch, integration_modules):
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "smoke.sqlite3"))

    nt = integration_modules["get_notetaker"]()
    nt.write(
        user_query="unified backend smoke test",
        assistant_response="smoke response",
        summary="smoke test entry",
        thread_id="smoke::unified",
    )
    results = nt.search(["smoke", "unified"], full_query="unified backend smoke test", limit=5)
    assert len(results) > 0
    assert any("smoke" in result.get("content", "").lower() for result in results)


def test_langchain_injection_shares_writes(tmp_path, monkeypatch, integration_modules):
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "shared.sqlite3"))

    shared_nt = integration_modules["get_notetaker"]()
    mem = integration_modules["MASEMemory"](notetaker=shared_nt)
    mem.save_context(
        inputs={"input": "injection test question"},
        outputs={"output": "injection test answer"},
    )
    results = shared_nt.search(["injection"], full_query="injection test", limit=3)
    assert len(results) > 0


def test_llamaindex_injection_shares_writes(tmp_path, monkeypatch, integration_modules):
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "llama-shared.sqlite3"))

    shared_nt = integration_modules["get_notetaker"]()
    mem = integration_modules["MASELlamaMemory"](notetaker=shared_nt)
    mem.put(types.SimpleNamespace(role="user", content="llama integration question"))
    mem.put(types.SimpleNamespace(role="assistant", content="llama integration answer"))
    results = shared_nt.search(["llama", "integration"], full_query="llama integration question", limit=3)
    assert len(results) > 0
