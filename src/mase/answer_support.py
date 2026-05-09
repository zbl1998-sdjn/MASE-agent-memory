from __future__ import annotations

import re
from typing import Any


def _terms(text: str) -> set[str]:
    return {term.lower() for term in re.findall(r"[\w-]{3,}", text) if not term.isdigit()}


def _sentences(answer: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", answer) if part.strip()]
    return parts or ([answer.strip()] if answer.strip() else [])


def _evidence_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("content", "entity_value", "entity_key", "category", "answer_preview", "user_question")
    )


def _best_evidence(sentence: str, evidence_rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    sentence_terms = _terms(sentence)
    if not sentence_terms:
        return None, 0.0
    best: tuple[dict[str, Any] | None, float] = (None, 0.0)
    for row in evidence_rows:
        evidence_terms = _terms(_evidence_text(row))
        if not evidence_terms:
            continue
        overlap = len(sentence_terms & evidence_terms)
        score = overlap / max(1, len(sentence_terms))
        if score > best[1]:
            best = (row, score)
    return best


def build_answer_support(answer: str, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    spans: list[dict[str, Any]] = []
    for index, sentence in enumerate(_sentences(answer)):
        evidence, score = _best_evidence(sentence, evidence_rows)
        stale = bool(evidence and evidence.get("superseded_at"))
        if stale:
            status = "stale"
        elif score >= 0.45:
            status = "supported"
        elif score > 0:
            status = "weak"
        else:
            status = "unsupported"
        spans.append(
            {
                "span_index": index,
                "text": sentence,
                "support_status": status,
                "support_score": round(score, 3),
                "evidence": evidence,
            }
        )
    summary = {
        "span_count": len(spans),
        "supported_count": sum(1 for span in spans if span["support_status"] == "supported"),
        "weak_count": sum(1 for span in spans if span["support_status"] == "weak"),
        "unsupported_count": sum(1 for span in spans if span["support_status"] == "unsupported"),
        "stale_count": sum(1 for span in spans if span["support_status"] == "stale"),
    }
    return {"answer": answer, "summary": summary, "spans": spans}


__all__ = ["build_answer_support"]
