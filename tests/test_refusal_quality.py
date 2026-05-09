from __future__ import annotations

from mase.refusal_quality import build_refusal_quality, is_refusal


def test_refusal_quality_detects_appropriate_refusal_without_evidence() -> None:
    report = build_refusal_quality("I do not know. There is no evidence.", [])

    assert is_refusal(report["answer"])
    assert report["classification"] == "appropriate_refusal"


def test_refusal_quality_flags_over_refusal_when_evidence_exists() -> None:
    report = build_refusal_quality(
        "I do not know.",
        [{"entity_key": "owner", "entity_value": "Alice owns the project"}],
    )

    assert report["classification"] == "over_refusal"
    assert report["severity"] == "high"


def test_refusal_quality_flags_unsupported_non_refusal() -> None:
    report = build_refusal_quality("Bob owns the project.", [])

    assert report["classification"] == "unsupported_answer"
