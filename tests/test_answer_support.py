from __future__ import annotations

from mase.answer_support import build_answer_support


def test_answer_support_maps_sentence_to_evidence() -> None:
    report = build_answer_support(
        "The project owner is Alice.",
        [{"category": "project", "entity_key": "owner", "entity_value": "Alice"}],
    )

    assert report["summary"]["supported_count"] == 1
    assert report["spans"][0]["support_status"] == "supported"


def test_answer_support_marks_unsupported_and_stale_spans() -> None:
    unsupported = build_answer_support("The budget is 9000.", [])
    stale = build_answer_support("The owner is Bob.", [{"content": "owner Bob", "superseded_at": "2026-01-01"}])

    assert unsupported["spans"][0]["support_status"] == "unsupported"
    assert stale["spans"][0]["support_status"] == "stale"
