from __future__ import annotations

from mase.quality_score import build_quality_report, score_fact, score_recall_hit, score_trace_summary


def test_fact_quality_penalizes_missing_provenance_and_privacy() -> None:
    score = score_fact({"category": "general_facts", "entity_key": "email", "entity_value": "alice@example.com"})

    assert score["grade"] in {"watch", "risk"}
    assert "missing_source_log_id" in score["risk_flags"]
    assert "privacy_finding" in score["risk_flags"]


def test_recall_quality_flags_superseded_hits() -> None:
    score = score_recall_hit({"_source": "memory_log", "content": "old fact", "superseded_at": "2026-01-01"})

    assert score["score"] < 0.8
    assert "superseded" in score["risk_flags"]


def test_quality_report_sorts_low_scores_first() -> None:
    report = build_quality_report(
        facts=[{"category": "general_facts", "entity_key": "owner", "entity_value": "alice", "source_log_id": 1}],
        recall_hits=[{"_source": "memory_log", "content": "old", "superseded_at": "2026-01-01"}],
        trace_summaries=[{"trace_id": "trace-1", "risk_flags": ["unsupported_answer"], "total_tokens": 10}],
    )

    assert report["summary"]["item_count"] == 3
    assert report["summary"]["risk_count"] == 2
    assert report["items"][0]["score"] <= report["items"][-1]["score"]


def test_trace_quality_penalizes_risk_flags() -> None:
    score = score_trace_summary({"trace_id": "trace-1", "risk_flags": ["scope_leak"], "answer_preview": "x"})

    assert score["grade"] in {"good", "watch"}
    assert score["risk_flags"] == ["scope_leak"]
