"""Lock-in tests for the 2026-04 orchestrator audit fix.

The audit found langgraph_orchestrator.py had 4 mocked nodes:
- router used keyword regex instead of RouterAgent.decide
- notetaker bypassed chat_with_tools
- planner had no model_interface
- action hardcoded `if "时间" in query`

These tests verify the rewritten nodes (a) route through the real LLM agents
when ``MASE_ORCHESTRATOR_FAST`` is unset, and (b) gracefully fall back to the
deterministic keyword path when it is set or when the LLM raises.
"""
from __future__ import annotations

import pytest

from src.mase import langgraph_orchestrator as orch


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch):
    monkeypatch.setattr(orch, "mase_model_interface", None)
    monkeypatch.setattr(orch, "executor_agent", None)
    monkeypatch.setattr(orch, "_router_agent", None)
    monkeypatch.setattr(orch, "_notetaker_agent", None)
    monkeypatch.setattr(orch, "_planner_agent", None)
    yield


def _state(query: str) -> dict:
    return {
        "messages": [],
        "user_query": query,
        "router_decision": "",
        "memory_context": "",
        "task_plan": "",
        "action_results": "",
        "executor_result": "",
        "error_log": [],
    }


def test_router_node_calls_real_llm_router(monkeypatch):
    """When fast-path is OFF, router_node must invoke RouterAgent.decide."""
    monkeypatch.delenv("MASE_ORCHESTRATOR_FAST", raising=False)
    captured: dict = {}

    class FakeRouter:
        def decide(self, user_question, system_prompt=None):
            captured["called_with"] = user_question
            return {"action": "search_memory", "keywords": ["alpha", "beta"]}

    monkeypatch.setattr(orch, "_get_router_agent", lambda: FakeRouter())
    out = orch.router_node(_state("我之前提到的项目代号是什么"))
    assert captured["called_with"] == "我之前提到的项目代号是什么"
    assert out["router_decision"] == "search_memory"
    assert "alpha" in out["memory_context"]


def test_router_node_fast_path_skips_llm(monkeypatch):
    """MASE_ORCHESTRATOR_FAST=1 must use keyword_router_decision, no LLM."""
    monkeypatch.setenv("MASE_ORCHESTRATOR_FAST", "1")

    def _boom():
        raise AssertionError("RouterAgent must NOT be constructed in fast-path")

    monkeypatch.setattr(orch, "_get_router_agent", _boom)
    out = orch.router_node(_state("我之前提到的项目"))
    assert out["router_decision"] in {"search_memory", "direct_answer"}


def test_router_node_falls_back_on_llm_error(monkeypatch):
    monkeypatch.delenv("MASE_ORCHESTRATOR_FAST", raising=False)

    class BrokenRouter:
        def decide(self, **kw):
            raise RuntimeError("ollama down")

    monkeypatch.setattr(orch, "_get_router_agent", lambda: BrokenRouter())
    out = orch.router_node(_state("hello"))
    assert out["router_decision"] in {"search_memory", "direct_answer"}
    assert any("router_llm_failed" in e for e in out.get("error_log", []))


def test_notetaker_node_calls_chat_with_tools(monkeypatch):
    """notetaker_node must route through NotetakerAgent.chat_with_tools (real LLM tool-loop)."""
    monkeypatch.delenv("MASE_ORCHESTRATOR_FAST", raising=False)
    captured: dict = {}

    class FakeNotetaker:
        def chat_with_tools(self, user_message, context="", mode=None):
            captured["user_message"] = user_message
            return {
                "tool_results": [
                    {
                        "name": "mase2_search_memory",
                        "result": [{"content": "项目代号 Aurora"}],
                    }
                ],
                "final_response": "已找到记忆: Aurora",
            }

        def execute_tool(self, *a, **kw):  # pragma: no cover - fast-path only
            raise AssertionError("execute_tool must not be called in LLM path")

    monkeypatch.setattr(orch, "_get_notetaker_agent", lambda: FakeNotetaker())
    state = _state("项目代号是什么")
    out = orch.notetaker_node(state)
    assert captured["user_message"] == "项目代号是什么"
    assert "Aurora" in out["memory_context"]


def test_planner_node_uses_model_interface(monkeypatch):
    """planner_node must NOT instantiate the bare DEFAULT_PLANNER."""
    monkeypatch.delenv("MASE_ORCHESTRATOR_FAST", raising=False)

    class FakePlanner:
        def plan(self, query, memory_context, mode=None):
            return f"PLAN({query[:6]})"

    monkeypatch.setattr(orch, "_get_planner_agent", lambda: FakePlanner())
    out = orch.planner_node(_state("how are you?"))
    assert out["task_plan"].startswith("PLAN(")
    # Must NOT be the legacy hardcoded fallback string.
    assert out["task_plan"] != "1. 结合查找到的记忆。\n2. 直接回答用户问题。"


def test_action_node_exposes_mcp_tools_to_llm(monkeypatch):
    """action_node must offer TOOL_REGISTRY as Function-Calling schemas."""
    monkeypatch.delenv("MASE_ORCHESTRATOR_FAST", raising=False)
    captured: dict = {}

    class FakeMI:
        def chat(self, agent_type, messages, tools=None, override_system_prompt=None, **kw):
            captured["tools"] = tools
            return {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "get_current_time", "arguments": "{}"}}
                    ],
                }
            }

    monkeypatch.setattr(orch, "_get_model_interface", lambda: FakeMI())
    state = _state("现在几点了")
    state["task_plan"] = "1. check time"
    out = orch.action_node(state)

    assert captured["tools"] is not None
    tool_names = {t["function"]["name"] for t in captured["tools"]}
    assert {"get_current_time", "read_local_file", "list_directory"} <= tool_names
    assert "get_current_time" in out["action_results"]


def test_action_node_fast_path_no_llm(monkeypatch):
    monkeypatch.setenv("MASE_ORCHESTRATOR_FAST", "1")

    def _boom():
        raise AssertionError("model_interface must NOT be touched in fast-path")

    monkeypatch.setattr(orch, "_get_model_interface", _boom)
    out = orch.action_node(_state("不相关问题"))
    assert out["action_results"] == ""
