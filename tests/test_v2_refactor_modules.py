"""Unit tests for the modules introduced during the V2 refactor."""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from mase.agent_registry import AgentRegistry, register_agent
from mase.circuit_breaker import state_for
from mase.config_schema import validate_config_path
from mase.event_bus import EventBus, Topics
from mase.health_tracker import CandidateHealthTracker
from mase.metrics import Metrics
from mase.model_call_ledger import ModelCallLedgerMixin
from mase.model_http import ModelHTTPMixin
from mase.model_interface import ModelInterface
from mase.model_providers import ModelProviderMixin
from mase.engine import MASESystem
from mase.engine_execution import EngineExecutionMixin
from mase.engine_notetaker import EngineNotetakerMixin
from mase.schema_migrations import current_version, latest_version, migrate


# ---------------------------------------------------------------------------
# event_bus
# ---------------------------------------------------------------------------
def test_event_bus_pubsub_and_prefix_match():
    bus = EventBus()
    received: list[tuple[str, dict]] = []
    unsub = bus.subscribe("mase.route", lambda e: received.append((e.topic, e.payload)))
    bus.publish(Topics.ROUTE_DECIDED, {"action": "search_memory"})
    bus.publish(Topics.RUN_DONE, {"answer_chars": 10})  # not matched
    assert len(received) == 1
    assert received[0][0] == Topics.ROUTE_DECIDED
    assert received[0][1]["action"] == "search_memory"
    unsub()
    bus.publish(Topics.ROUTE_DECIDED, {"action": "ignored"})
    assert len(received) == 1


def test_event_bus_swallows_subscriber_errors():
    bus = EventBus()
    bus.subscribe("mase", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.publish(Topics.RUN_DONE, {})
    errors = bus.drain_errors()
    assert any("boom" in repr(e) for e in errors)


# ---------------------------------------------------------------------------
# agent_registry
# ---------------------------------------------------------------------------
def test_agent_registry_register_and_resolve():
    registry = AgentRegistry()

    class _Dummy:
        def __init__(self, model_interface, config_path):
            self.model_interface = model_interface
            self.config_path = config_path

    registry.register("dummy_test_agent", _Dummy)
    spec = registry.get("dummy_test_agent")
    assert spec is not None
    out = spec.factory("mi", "cfg")
    assert isinstance(out, _Dummy)
    assert out.model_interface == "mi"
    assert "dummy_test_agent" in registry.names()


def test_agent_registry_replace_silently():
    registry = AgentRegistry()
    registry.register("dup", lambda mi, cp: "first")
    registry.register("dup", lambda mi, cp: "second")
    assert registry.get("dup").factory(None, None) == "second"


def test_register_agent_decorator_uses_global_registry():
    @register_agent("decorator_test_agent")
    class _Decorated:
        def __init__(self, mi, cp):
            self.value = "ok"

    from mase.agent_registry import get_registry

    spec = get_registry().get("decorator_test_agent")
    assert spec is not None
    assert spec.factory(None, None).value == "ok"
    get_registry().unregister("decorator_test_agent")


# ---------------------------------------------------------------------------
# health_tracker
# ---------------------------------------------------------------------------
def test_health_tracker_demotes_failures():
    tr = CandidateHealthTracker(cooldown_failures=2, cooldown_seconds=60)
    tr.record_success("cloud", "good", latency_ms=100)
    tr.record_failure("cloud", "bad")
    tr.record_failure("cloud", "bad")
    candidates = [{"provider": "cloud", "model_name": "bad"}, {"provider": "cloud", "model_name": "good"}]
    sorted_ = tr.sort_candidates(candidates)
    assert sorted_[0]["model_name"] == "good"
    assert sorted_[-1]["model_name"] == "bad"


def test_health_tracker_local_preference_when_unknown():
    tr = CandidateHealthTracker()
    candidates = [
        {"provider": "deepseek", "model_name": "deepseek-chat"},
        {"provider": "ollama", "model_name": "qwen2.5:7b"},
    ]
    sorted_ = tr.sort_candidates(candidates)
    # No history → both have success_rate=1.0; tracker should be stable.
    assert {c["provider"] for c in sorted_} == {"deepseek", "ollama"}


# ---------------------------------------------------------------------------
# circuit_breaker
# ---------------------------------------------------------------------------
def test_circuit_breaker_state_transitions():
    tr = CandidateHealthTracker(cooldown_failures=2, cooldown_seconds=999)
    tr.record_success("p", "m")
    assert state_for("p", "m", tracker=tr).state == "closed"
    tr.record_failure("p", "m")
    assert state_for("p", "m", tracker=tr).state == "closed"  # 1 failure < 2
    tr.record_failure("p", "m")
    s = state_for("p", "m", tracker=tr)
    assert s.state == "open"
    assert s.seconds_until_retry > 0


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def test_metrics_aggregates_counts_and_latency():
    bus = EventBus()
    metrics = Metrics()
    # Wire metrics to OUR test bus rather than the global one.
    metrics._unsubscribe = bus.subscribe("mase", metrics._on_event)  # noqa: SLF001
    bus.publish(Topics.EXECUTOR_CALL_DONE, {"latency_ms": 100})
    bus.publish(Topics.EXECUTOR_CALL_DONE, {"latency_ms": 200})
    bus.publish(Topics.RUN_DONE, {})
    snap = metrics.snapshot()
    assert snap["event_counters"][Topics.EXECUTOR_CALL_DONE] == 2
    assert snap["event_counters"][Topics.RUN_DONE] == 1
    assert snap["latency_ms_avg"][Topics.EXECUTOR_CALL_DONE] == 150.0
    text = metrics.format_prometheus()
    assert "mase_events_total" in text


# ---------------------------------------------------------------------------
# model_interface split
# ---------------------------------------------------------------------------
def test_model_interface_uses_call_ledger_mixin():
    assert issubclass(ModelInterface, ModelCallLedgerMixin)
    assert "_build_call_ledger" not in ModelInterface.__dict__
    assert ModelInterface._build_call_ledger is ModelCallLedgerMixin._build_call_ledger


def test_model_interface_uses_http_mixin():
    assert issubclass(ModelInterface, ModelHTTPMixin)
    assert "_get_http_client" not in ModelInterface.__dict__
    assert ModelInterface._get_http_client is ModelHTTPMixin._get_http_client


def test_model_interface_uses_provider_mixin():
    assert issubclass(ModelInterface, ModelProviderMixin)
    assert "_call_openai" not in ModelInterface.__dict__
    assert ModelInterface._call_openai is ModelProviderMixin._call_openai


# ---------------------------------------------------------------------------
# engine split
# ---------------------------------------------------------------------------
def test_mase_system_uses_notetaker_mixin():
    assert issubclass(MASESystem, EngineNotetakerMixin)
    assert "_build_fact_sheet_with_notetaker" not in MASESystem.__dict__
    assert MASESystem._build_fact_sheet_with_notetaker is EngineNotetakerMixin._build_fact_sheet_with_notetaker


def test_mase_system_uses_execution_mixin():
    assert issubclass(MASESystem, EngineExecutionMixin)
    assert "call_executor" not in MASESystem.__dict__
    assert MASESystem.call_executor is EngineExecutionMixin.call_executor


# ---------------------------------------------------------------------------
# config_schema
# ---------------------------------------------------------------------------
def test_config_schema_lenient_accepts_real_config():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = os.path.join(repo, "config.json")
    if not os.path.exists(cfg):
        pytest.skip("config.json not found")
    parsed, messages = validate_config_path(cfg, strict=False, emit_events=False)
    assert parsed is not None, f"validate_config_path returned None: {messages}"


def test_config_schema_strict_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"models": {"executor": {}}}))  # missing required modes
    with pytest.raises(Exception):
        validate_config_path(str(bad), strict=True, emit_events=False)


# ---------------------------------------------------------------------------
# schema_migrations
# ---------------------------------------------------------------------------
def test_schema_migrations_idempotent(tmp_path):
    db = tmp_path / "m.sqlite"
    res1 = migrate(db)
    assert res1 == {"from": 0, "to": latest_version()}
    res2 = migrate(db)
    assert res2 == {"from": latest_version(), "to": latest_version()}
    conn = sqlite3.connect(db)
    try:
        assert current_version(conn) == latest_version()
        # Tables exist
        rows = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','virtual')")}
        assert "memory_log" in rows
        assert "schema_version" in rows
    finally:
        conn.close()
