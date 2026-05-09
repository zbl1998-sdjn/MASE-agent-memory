from __future__ import annotations

import re
import uuid
from typing import Any, Protocol


class MemoryReader(Protocol):
    def list_facts(self, category: str | None = None, *, scope_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def recall_timeline(
        self,
        *,
        thread_id: str | None = None,
        limit: int = 50,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_fact_history(
        self,
        *,
        category: str | None = None,
        entity_key: str | None = None,
        limit: int = 50,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


def _terms_from_case(case: dict[str, Any]) -> list[str]:
    parts = [str(case.get("symptom") or ""), str(case.get("issue_type") or "")]
    evidence = case.get("evidence")
    if isinstance(evidence, dict):
        parts.extend(str(value) for value in evidence.values() if value is not None)
    text = " ".join(parts).lower()
    terms = [term for term in re.findall(r"[\w-]{3,}", text) if not term.isdigit()]
    return list(dict.fromkeys(terms))[:16]


def _row_text(row: dict[str, Any]) -> str:
    values = [
        row.get("category"),
        row.get("entity_key"),
        row.get("entity_value"),
        row.get("content"),
        row.get("thread_id"),
        row.get("role"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _score_row(row: dict[str, Any], terms: list[str]) -> int:
    text = _row_text(row)
    return sum(1 for term in terms if term in text)


def _top_rows(rows: list[dict[str, Any]], terms: list[str], *, limit: int) -> list[dict[str, Any]]:
    ranked = [(row, _score_row(row, terms)) for row in rows]
    selected = [(row, score) for row, score in ranked if score > 0]
    selected.sort(key=lambda item: item[1], reverse=True)
    return [{**row, "_repair_match_score": score} for row, score in selected[:limit]]


def _fact_operation(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": "propose_fact_supersede_or_upsert",
        "status": "proposal_only",
        "target": {
            "category": candidate.get("category"),
            "entity_key": candidate.get("entity_key"),
            "current_value": candidate.get("entity_value"),
            "source_log_id": candidate.get("source_log_id"),
        },
        "requires": ["new_value", "supporting_evidence", "validation_query"],
        "risk": "Do not overwrite silently; create a correction/supersede path with source evidence.",
    }


def build_repair_diff(case: dict[str, Any], memory: MemoryReader) -> dict[str, Any]:
    scope = dict(case.get("scope") or {})
    terms = _terms_from_case(case)
    facts = memory.list_facts(scope_filters=scope)
    timeline = memory.recall_timeline(limit=100, scope_filters=scope)
    history = memory.get_fact_history(limit=100, scope_filters=scope)
    fact_candidates = _top_rows(facts, terms, limit=5)
    event_candidates = _top_rows(timeline, terms, limit=5)
    history_candidates = _top_rows(history, terms, limit=5)
    operations: list[dict[str, Any]] = []
    if fact_candidates:
        operations.append(_fact_operation(fact_candidates[0]))
    else:
        operations.append(
            {
                "operation": "propose_missing_fact_upsert",
                "status": "proposal_only",
                "target": {"scope": scope},
                "requires": ["category", "entity_key", "entity_value", "supporting_source_log_id"],
                "risk": "No matching current fact was found; require evidence before adding memory.",
            }
        )
    if event_candidates:
        operations.append(
            {
                "operation": "propose_correction_event",
                "status": "proposal_only",
                "target": {
                    "thread_id": event_candidates[0].get("thread_id"),
                    "source_event_id": event_candidates[0].get("id") or event_candidates[0].get("log_id"),
                },
                "requires": ["corrected_utterance", "extra_keywords"],
                "risk": "Correction must preserve tenant/workspace/visibility scope.",
            }
        )
    return {
        "proposal_id": f"diff_{uuid.uuid4().hex[:16]}",
        "case_id": case.get("case_id"),
        "issue_type": case.get("issue_type"),
        "scope": scope,
        "match_terms": terms,
        "diagnosis": {
            "fact_candidate_count": len(fact_candidates),
            "event_candidate_count": len(event_candidates),
            "history_candidate_count": len(history_candidates),
            "confidence": "medium" if fact_candidates or event_candidates else "low",
        },
        "candidates": {
            "facts": fact_candidates,
            "events": event_candidates,
            "history": history_candidates,
        },
        "proposed_operations": operations,
        "validation": {
            "queries": [str(case.get("symptom") or ""), *terms[:3]],
            "must_check": [
                "Recall returns the corrected fact in the same scope.",
                "Trace evidence points to active, non-superseded rows.",
                "No cross-tenant or visibility leak is introduced.",
            ],
        },
        "execution_allowed": False,
    }


__all__ = ["MemoryReader", "build_repair_diff"]
