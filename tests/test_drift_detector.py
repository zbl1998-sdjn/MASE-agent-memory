from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mase.drift_detector import detect_memory_drift

UTC = timezone.utc


def test_drift_detector_flags_conflicting_fact_values() -> None:
    report = detect_memory_drift(
        [
            {"category": "project", "entity_key": "owner", "entity_value": "Alice"},
            {"category": "project", "entity_key": "owner", "entity_value": "Bob"},
        ]
    )

    assert report["summary"]["status"] == "attention_required"
    assert report["issues"][0]["kind"] == "conflicting_fact_values"


def test_drift_detector_flags_duplicate_values_and_stale_pressure() -> None:
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    report = detect_memory_drift(
        [
            {"category": "project", "entity_key": "owner", "entity_value": "Alice", "will_expire_at": expires},
            {"category": "project", "entity_key": "lead", "entity_value": "Alice"},
        ]
    )

    kinds = {issue["kind"] for issue in report["issues"]}
    assert "duplicate_fact_value" in kinds
    assert "stale_memory_pressure" in kinds
