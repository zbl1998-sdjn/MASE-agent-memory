from __future__ import annotations

from typing import Any

import mase.metrics as metrics_module
from mase.event_bus import Event
from mase.metrics import Metrics
from mase.refusal_quality import build_refusal_quality, is_refusal


def test_metrics_install_uninstall_snapshot_and_prometheus(monkeypatch) -> None:
    subscribe_calls: list[str] = []
    unsubscribe_calls: list[str] = []

    class FakeBus:
        def subscribe(self, pattern: str, handler: Any) -> Any:
            del handler
            subscribe_calls.append(pattern)

            def unsubscribe() -> None:
                unsubscribe_calls.append(pattern)

            return unsubscribe

    class FakeTracker:
        def snapshot(self) -> list[dict[str, Any]]:
            return [
                {
                    "provider": "openai",
                    "model": "gpt-test",
                    "success_rate": 0.75,
                    "total_calls": 4,
                    "total_failures": 1,
                }
            ]

    monkeypatch.setattr(metrics_module, "get_bus", lambda: FakeBus())
    monkeypatch.setattr(metrics_module, "get_tracker", lambda: FakeTracker())

    metrics = Metrics()
    metrics.install()
    metrics.install()
    assert subscribe_calls == ["mase"]
    metrics.uninstall()
    assert unsubscribe_calls == ["mase"]

    metrics._unsubscribe = lambda: (_ for _ in ()).throw(RuntimeError("ignore unsubscribe failure"))
    metrics.uninstall()
    assert metrics._unsubscribe is None

    metrics._on_event(Event("mase.executor.done", {"latency_ms": 12.5}))
    metrics._on_event(Event("mase.executor.done", {"latency_ms": -1}))
    metrics._on_event(Event("mase.model.failed", {}))
    snap = metrics.snapshot()
    assert snap["event_counters"] == {"mase.executor.done": 2, "mase.model.failed": 1}
    assert snap["latency_ms_avg"] == {"mase.executor.done": 12.5}

    prometheus = metrics.format_prometheus()
    assert 'mase_events_total{topic="mase.executor.done"} 2' in prometheus
    assert 'mase_candidate_success_rate{provider="openai",model="gpt-test"} 0.7500' in prometheus

    metrics.reset()
    assert metrics.snapshot()["event_counters"] == {}


def test_refusal_quality_classifies_all_recommendation_paths() -> None:
    assert is_refusal("I don't know from the evidence.") is True
    assert is_refusal("Alice is the owner.") is False

    over_refusal = build_refusal_quality("I don't know.", [{"content": "Alice is the owner."}])
    assert over_refusal["classification"] == "over_refusal"
    assert over_refusal["severity"] == "high"

    appropriate = build_refusal_quality("No evidence.", [])
    assert appropriate["classification"] == "appropriate_refusal"
    assert appropriate["severity"] == "low"

    unsupported = build_refusal_quality("Banana spaceship.", [])
    assert unsupported["classification"] == "unsupported_answer"
    assert unsupported["recommended_actions"] == ["要求 agent 改为无证据拒答", "创建 repair case 检查错误记忆或错误召回"]

    partial = build_refusal_quality(
        "Alice is the owner. Banana spaceship.",
        [{"content": "Alice is the owner."}],
    )
    assert partial["classification"] == "partially_supported_answer"

    supported = build_refusal_quality("Alice is the owner.", [{"content": "Alice is the owner."}])
    assert supported["classification"] == "supported_answer"
    assert supported["recommended_actions"] == ["保留样本作为黄金测试候选"]
