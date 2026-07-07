"""notetaker 事件→事实实时链接(投影切片②):upsert 自动绑定最近 user 事件。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.notetaker_agent import NotetakerAgent  # noqa: E402


def _spy_agent(monkeypatch) -> tuple[NotetakerAgent, list[dict[str, Any]]]:
    agent = NotetakerAgent(model_interface=None)
    upserts: list[dict[str, Any]] = []

    def _fake_write(thread_id: str, role: str, content: str, **kw: Any) -> str:
        return "Success: Event logged with ID 77"

    def _fake_upsert(category: str, key: str, value: str, **kw: Any) -> str:
        upserts.append({"category": category, "key": key, "value": value, **kw})
        return "Success: Fact updated"

    monkeypatch.setitem(agent._tool_handlers, "mase2_write_interaction", _fake_write)
    monkeypatch.setitem(agent._tool_handlers, "mase2_upsert_fact", _fake_upsert)
    return agent, upserts


def test_upsert_binds_latest_user_event(monkeypatch):
    agent, upserts = _spy_agent(monkeypatch)
    agent.execute_tool("mase2_write_interaction", {"thread_id": "t", "role": "user", "content": "预算: 500 元"})
    agent.execute_tool("mase2_upsert_fact", {"category": "context", "key": "预算", "value": "500 元"})
    assert upserts[0]["source_log_id"] == 77


def test_assistant_event_does_not_update_binding(monkeypatch):
    agent, upserts = _spy_agent(monkeypatch)
    agent.execute_tool("mase2_write_interaction", {"thread_id": "t", "role": "assistant", "content": "好的"})
    agent.execute_tool("mase2_upsert_fact", {"category": "context", "key": "k", "value": "v"})
    assert "source_log_id" not in upserts[0]


def test_explicit_source_log_id_is_not_overridden(monkeypatch):
    agent, upserts = _spy_agent(monkeypatch)
    agent.execute_tool("mase2_write_interaction", {"thread_id": "t", "role": "user", "content": "x"})
    agent.execute_tool("mase2_upsert_fact", {"category": "c", "key": "k", "value": "v", "source_log_id": 5})
    assert upserts[0]["source_log_id"] == 5


def test_no_injection_before_any_user_event(monkeypatch):
    agent, upserts = _spy_agent(monkeypatch)
    agent.execute_tool("mase2_upsert_fact", {"category": "c", "key": "k", "value": "v"})
    assert "source_log_id" not in upserts[0]
