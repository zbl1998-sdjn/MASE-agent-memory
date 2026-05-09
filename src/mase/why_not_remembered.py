from __future__ import annotations

from typing import Any, Protocol


class MemoryDiagnosticReader(Protocol):
    def list_facts(self, category: str | None = None, *, scope_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def recall_timeline(
        self,
        *,
        thread_id: str | None = None,
        limit: int = 50,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def search_memory(
        self,
        keywords: list[str],
        *,
        full_query: str | None = None,
        limit: int = 5,
        include_history: bool = False,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


def _terms(query: str) -> list[str]:
    return [part for part in query.split() if len(part) >= 2] or [query]


def diagnose_why_not_remembered(
    *,
    query: str,
    memory: MemoryDiagnosticReader,
    scope: dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    scope_filters = dict(scope or {})
    timeline = memory.recall_timeline(thread_id=thread_id, limit=100, scope_filters=scope_filters)
    facts = memory.list_facts(scope_filters=scope_filters)
    recall_hits = memory.search_memory(_terms(query), full_query=query, limit=10, include_history=True, scope_filters=scope_filters)
    stages: list[dict[str, Any]] = []
    stages.append(
        {
            "stage": "event_log",
            "status": "pass" if timeline else "fail",
            "evidence_count": len(timeline),
            "hint": None if timeline else "No scoped event log rows found; the notetaker may never received/wrote the memory.",
        }
    )
    stages.append(
        {
            "stage": "entity_state",
            "status": "pass" if facts else "fail",
            "evidence_count": len(facts),
            "hint": None if facts else "No scoped current facts found; event evidence may not have been consolidated into facts.",
        }
    )
    stages.append(
        {
            "stage": "recall",
            "status": "pass" if recall_hits else "fail",
            "evidence_count": len(recall_hits),
            "hint": None if recall_hits else "Query terms did not retrieve matching facts/events in this scope.",
        }
    )
    superseded = [row for row in recall_hits if row.get("superseded_at")]
    if superseded:
        stages.append(
            {
                "stage": "supersede_filter",
                "status": "warn",
                "evidence_count": len(superseded),
                "hint": "Some retrieved evidence is superseded; answer path may intentionally ignore old memory.",
            }
        )
    scope_empty = not any(scope_filters.values())
    if scope_empty:
        stages.append(
            {
                "stage": "scope",
                "status": "warn",
                "evidence_count": 0,
                "hint": "No explicit tenant/workspace/visibility scope was provided; check whether the memory exists in another scope.",
            }
        )
    failing = [stage for stage in stages if stage["status"] == "fail"]
    likely_cause = failing[0]["stage"] if failing else "query_or_answer_path" if not recall_hits else "memory_available"
    return {
        "query": query,
        "scope": scope_filters,
        "thread_id": thread_id,
        "likely_cause": likely_cause,
        "stages": stages,
        "samples": {
            "timeline": timeline[:5],
            "facts": facts[:5],
            "recall_hits": recall_hits[:5],
        },
        "recommended_actions": _recommended_actions(likely_cause),
    }


def _recommended_actions(cause: str) -> list[str]:
    if cause == "event_log":
        return ["Check write path and notetaker input.", "Ask the memory agent to write the missing event with explicit scope."]
    if cause == "entity_state":
        return ["Run Write Inspector.", "Ask the memory agent to consolidate supported event evidence into a fact."]
    if cause == "recall":
        return ["Try query variants in Recall Lab.", "Check category/key naming and scope filters."]
    if cause == "memory_available":
        return ["Use Answer Support View to verify whether the answer ignored available memory."]
    return ["Compare trace route, fact sheet, and executor target."]


__all__ = ["diagnose_why_not_remembered"]
