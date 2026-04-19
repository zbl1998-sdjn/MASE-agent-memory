from __future__ import annotations

import json
from pathlib import Path

from mase_tools.legacy import extract_question_scope_filters, write_interaction


def test_extract_question_scope_filters_uses_reference_time_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/05/30 (Tue) 23:40")
    scope_filters = extract_question_scope_filters("What did I do last week?")
    temporal_range = scope_filters.get("temporal_range")

    assert scope_filters["strict"] is True
    assert temporal_range is not None
    assert temporal_range["start"] == "2023-05-22T00:00:00"
    assert temporal_range["end"] == "2023-05-28T23:59:59"


def test_write_interaction_preserves_source_timestamp(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
    filepath = Path(
        write_interaction(
            user_query="I booked the trip.",
            assistant_response="",
            summary="Booked the trip.",
            metadata={"timestamp": "2023/05/30 (Tue) 23:40"},
        )
    )
    record = json.loads(filepath.read_text(encoding="utf-8"))

    assert filepath.parent.name == "2023-05-30"
    assert record["timestamp"] == "2023-05-30T23:40:00"
    assert record["metadata"]["source_timestamp"] == "2023-05-30T23:40:00"
    assert record["metadata"]["ingested_at"]
