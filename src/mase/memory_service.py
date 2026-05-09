from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mase_tools.memory import api
from mase_tools.memory.db_core import fetch_memory_rows


@dataclass
class MemoryService:
    @staticmethod
    def _scope(scope_filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return {key: value for key, value in dict(scope_filters or {}).items() if value not in (None, "")}

    @staticmethod
    def _source_counts(hits: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in hits:
            source = str(item.get("_source") or "unknown")
            counts[source] = counts.get(source, 0) + 1
        return counts

    @staticmethod
    def _scope_mismatches(row: dict[str, Any], scope: dict[str, Any]) -> list[str]:
        mismatches: list[str] = []
        for key, expected in scope.items():
            actual = row.get(key)
            if actual not in (None, "", expected):
                mismatches.append(key)
        return mismatches

    def _inspect_recall_hits(self, hits: list[dict[str, Any]], scope: dict[str, Any]) -> list[dict[str, Any]]:
        inspections: list[dict[str, Any]] = []
        for rank, item in enumerate(hits, start=1):
            source = str(item.get("_source") or item.get("source") or "unknown")
            freshness = str(item.get("freshness") or "")
            conflict = str(item.get("conflict_status") or "")
            scope_mismatches = self._scope_mismatches(item, scope)
            risk_flags: list[str] = []
            if item.get("superseded_at"):
                risk_flags.append("superseded_event")
            if freshness and freshness not in {"fresh", "current"}:
                risk_flags.append(f"freshness:{freshness}")
            if conflict and conflict not in {"none", "resolved"}:
                risk_flags.append(f"conflict:{conflict}")
            if scope_mismatches:
                risk_flags.append(f"scope_mismatch:{','.join(scope_mismatches)}")
            inspections.append(
                {
                    "rank": rank,
                    "source": source,
                    "evidence_type": "current_fact" if source == "entity_state" else "event_evidence",
                    "selected_reason": item.get("retrieval_reason") or item.get("source_reason") or source,
                    "freshness": freshness or "unknown",
                    "conflict_status": conflict or "unknown",
                    "scope_mismatches": scope_mismatches,
                    "risk_flags": risk_flags,
                    "category": item.get("category"),
                    "entity_key": item.get("entity_key"),
                    "thread_id": item.get("thread_id"),
                    "content_preview": str(item.get("entity_value") or item.get("content") or "")[:240],
                }
            )
        return inspections

    def remember_event(
        self,
        thread_id: str,
        role: str,
        content: str,
        *,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(scope_filters)
        result = api.mase2_write_interaction(thread_id, role, content, scope_filters=scope)
        return {"thread_id": thread_id, "role": role, "result": result, "scope": scope}

    def upsert_fact(
        self,
        category: str,
        key: str,
        value: str,
        *,
        reason: str | None = None,
        source_log_id: int | None = None,
        importance_score: float | None = None,
        ttl_days: int | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(scope_filters)
        api.upsert_entity_fact(
            category,
            key,
            value,
            reason=reason,
            source_log_id=source_log_id,
            importance_score=importance_score,
            ttl_days=ttl_days,
            **scope,
        )
        return {"category": category, "key": key, "value": value, "scope": scope}

    def list_facts(
        self,
        category: str | None = None,
        *,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return api.mase2_get_facts(category, scope_filters=self._scope(scope_filters))

    def recall_current_state(
        self,
        keywords: list[str],
        *,
        limit: int = 5,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return api.mase2_search_entity_facts(
            keywords,
            limit=limit,
            scope_filters=self._scope(scope_filters),
        )

    def search_memory(
        self,
        keywords: list[str],
        *,
        full_query: str | None = None,
        limit: int = 5,
        include_history: bool = False,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        scope = self._scope(scope_filters)
        return api.mase2_facts_first_recall(
            keywords,
            full_query=full_query,
            limit=limit,
            include_history=include_history,
            scope_filters=scope,
        )

    def recall_timeline(
        self,
        *,
        thread_id: str | None = None,
        limit: int = 50,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        rows = fetch_memory_rows(
            limit=limit,
            chronological=True,
            include_superseded=True,
            **self._scope(scope_filters),
        )
        if thread_id is None:
            return rows
        return [row for row in rows if str(row.get("thread_id") or "") == thread_id]

    def correct_memory(
        self,
        thread_id: str,
        utterance: str,
        *,
        extra_keywords: list[str] | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return api.mase2_correct_and_log(
            thread_id,
            utterance,
            extra_keywords=extra_keywords,
            scope_filters=self._scope(scope_filters),
        )

    def get_fact_history(
        self,
        *,
        category: str | None = None,
        entity_key: str | None = None,
        limit: int = 50,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return api.mase2_get_fact_history(
            category=category,
            entity_key=entity_key,
            limit=limit,
            scope_filters=self._scope(scope_filters),
        )

    def upsert_session_state(
        self,
        session_id: str,
        context_key: str,
        context_value: str,
        *,
        ttl_days: int | None = None,
        metadata: dict[str, Any] | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return api.mase2_upsert_session_context(
            session_id,
            context_key,
            context_value,
            ttl_days=ttl_days,
            metadata=metadata,
            scope_filters=self._scope(scope_filters),
        )

    def get_session_state(
        self,
        session_id: str,
        *,
        include_expired: bool = False,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return api.mase2_get_session_context(
            session_id,
            include_expired=include_expired,
            scope_filters=self._scope(scope_filters),
        )

    def register_procedure(
        self,
        procedure_key: str,
        content: str,
        *,
        procedure_type: str = "rule",
        metadata: dict[str, Any] | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return api.mase2_register_procedure(
            procedure_key,
            content,
            procedure_type=procedure_type,
            metadata=metadata,
            scope_filters=self._scope(scope_filters),
        )

    def list_procedures(
        self,
        procedure_type: str | None = None,
        *,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return api.mase2_list_procedures(
            procedure_type=procedure_type,
            scope_filters=self._scope(scope_filters),
        )

    def consolidate_session(
        self,
        thread_id: str,
        *,
        max_items: int = 50,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return api.mase2_consolidate_session(
            thread_id,
            max_items=max_items,
            scope_filters=self._scope(scope_filters),
        )

    def list_episodic_snapshots(
        self,
        thread_id: str | None = None,
        *,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return api.mase2_list_episodic_snapshots(
            thread_id=thread_id,
            scope_filters=self._scope(scope_filters),
        )

    def forget(
        self,
        *,
        category: str | None = None,
        entity_key: str | None = None,
        session_id: str | None = None,
        context_key: str | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(scope_filters)
        if category and entity_key:
            return api.mase2_forget_fact(category, entity_key, scope_filters=scope)
        if session_id:
            return api.mase2_forget_session_context(
                session_id,
                context_key=context_key,
                scope_filters=scope,
            )
        raise ValueError("forget requires either (category, entity_key) or session_id")

    def explain_memory_answer(
        self,
        query: str,
        *,
        limit: int = 5,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(scope_filters)
        keywords = [part for part in query.split() if part]
        hits = self.search_memory(
            keywords or [query],
            full_query=query,
            limit=limit,
            include_history=True,
            scope_filters=scope,
        )
        hit_inspections = self._inspect_recall_hits(hits, scope)
        return {
            "query": query,
            "scope": scope,
            "hits": hits,
            "hit_inspections": hit_inspections,
            "summary": [item.get("retrieval_reason") or item.get("_source") for item in hits],
            "metadata": {
                "hit_count": len(hits),
                "source_counts": self._source_counts(hits),
                "has_current_state": any(item.get("_source") == "entity_state" for item in hits),
                "risk_count": sum(1 for item in hit_inspections if item.get("risk_flags")),
            },
        }

    def validate_memory(self, *, scope_filters: dict[str, Any] | None = None) -> dict[str, Any]:
        scope = self._scope(scope_filters)
        facts = api.mase2_get_facts(scope_filters=scope)
        procedures = self.list_procedures(scope_filters=scope)
        session_rows = api.mase2_get_session_context("default", include_expired=True, scope_filters=scope)
        return {
            "fact_count": len(facts),
            "procedure_count": len(procedures),
            "session_state_rows": len(session_rows),
            "scope": scope,
        }


__all__ = ["MemoryService"]
