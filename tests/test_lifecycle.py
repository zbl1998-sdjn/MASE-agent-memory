from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mase.lifecycle import build_lifecycle_report, classify_fact_lifecycle, validate_fact_contract


def test_lifecycle_classifies_expiring_and_long_term_facts() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    expiring = classify_fact_lifecycle(
        {"will_expire_at": (now + timedelta(days=2)).isoformat(), "importance_score": 0.4},
        now=now,
    )
    long_term = classify_fact_lifecycle({"ttl_days": None, "importance_score": 0.9}, now=now)

    assert expiring["state"] == "expiring_soon"
    assert long_term["state"] == "long_term_fact"


def test_lifecycle_contract_flags_missing_and_unknown_fields() -> None:
    violations = validate_fact_contract({"category": "unknown_category", "entity_key": "", "entity_value": "x"})

    assert any(item["field"] == "entity_key" for item in violations)
    assert any(item["field"] == "category" and item["severity"] == "warning" for item in violations)


def test_lifecycle_report_summarizes_contracts() -> None:
    report = build_lifecycle_report(
        [
            {"category": "general_facts", "entity_key": "owner", "entity_value": "alice", "importance_score": 0.8},
            {"category": "unknown_category", "entity_key": "", "entity_value": "bad"},
        ]
    )

    assert report["summary"]["fact_count"] == 2
    assert report["summary"]["by_state"]["long_term_fact"] == 1
    assert report["summary"]["contract_violation_count"] >= 1
