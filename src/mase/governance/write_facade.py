"""Governed write facade for legacy notetaker fact writes.

The facade is the migration bridge between ``entity_state`` and governed facts:
legacy reads keep working, while enterprise mode records every notetaker fact as
a candidate and admits only mechanically grounded facts into active memory.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from .fact_contract import ClaimType, FactContract, utc_now
from .fact_store import propose_fact


@dataclass(frozen=True)
class GovernedFactWriteResult:
    """Outcome of a legacy-to-governance candidate write."""

    candidate_id: str
    fact_id: str | None
    fact_status: str | None
    candidate_recorded: bool
    governance_error: str | None = None


def governance_dual_write_enabled() -> bool:
    """Return whether legacy notetaker facts should dual-write to governance."""
    for name in ("MASE_ENTERPRISE_MODE", "MASE_GOVERNANCE_DUAL_WRITE"):
        value = os.environ.get(name, "").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
    return False


class GovernedFactWriteFacade:
    """Bridge notetaker fact writes into governed fact candidates.

    Failure behavior:
        Candidate recording and governed fact proposal are best-effort for the
        legacy API.  Errors are recorded on the candidate row and returned to the
        caller so the write path can leave an explicit warning without breaking
        existing entity_state behavior.
    """

    def record_notetaker_fact(
        self,
        category: str,
        key: str,
        value: str,
        *,
        reason: str | None = None,
        source_log_id: int | None = None,
        source_media_id: int | None = None,
        scope_filters: dict[str, Any] | None = None,
        evidence_text: str | None = None,
        evidence_source_type: str | None = None,
        evidence_source_id: str | None = None,
        evidence_trust_level: int | None = None,
        evidence_full_text: str | None = None,
        db_path: str | Path | None = None,
    ) -> GovernedFactWriteResult:
        """Record a candidate and submit it to governed admission.

        Invariant:
            A notetaker fact with no source text is treated as inference and
            cannot become active.  It remains visible in the review queue.
        """
        scope = {key_: value_ for key_, value_ in dict(scope_filters or {}).items() if value_ not in (None, "")}
        source_text = evidence_full_text
        if source_text is None and source_log_id is not None:
            source_text = _memory_log_content(source_log_id, db_path=db_path)
        source_text = source_text or ""
        evidence = evidence_text or _default_evidence_text(category, key, value)
        source_type = evidence_source_type or ("memory_log" if source_log_id is not None else "notetaker_inference")
        source_id = evidence_source_id or (str(source_log_id) if source_log_id is not None else "notetaker")
        trust_level = int(evidence_trust_level if evidence_trust_level is not None else _default_trust(value, source_text))
        claim_type = _claim_type_for_category(category, source_text=source_text, value=value)
        candidate_id = _record_candidate(
            category=category,
            key=key,
            value=value,
            reason=reason,
            source_log_id=source_log_id,
            source_media_id=source_media_id,
            source_type=source_type,
            source_id=source_id,
            evidence_text=evidence,
            source_full_text=source_text,
            trust_level=trust_level,
            scope=scope,
            db_path=db_path,
        )
        try:
            fact = propose_fact(
                FactContract(
                    fact_id=f"fact_{uuid.uuid4().hex}",
                    entity_id="user:default",
                    claim_type=claim_type,
                    subject=category,
                    predicate=key,
                    object_value=value,
                    confidence=1.0,
                    observed_at=utc_now(),
                    confidence_basis={
                        "method": "governed_notetaker_dual_write",
                        "producer": "GovernedFactWriteFacade",
                        "calibrated": False,
                        "candidate_id": candidate_id,
                    },
                    tenant_id=str(scope.get("tenant_id") or ""),
                    workspace_id=str(scope.get("workspace_id") or ""),
                    visibility=str(scope.get("visibility") or "private"),
                ),
                evidence,
                source_type=source_type,
                source_id=source_id,
                trust_level=trust_level,
                source_full_text=source_text,
                db_path=db_path,
            )
            _update_candidate(
                candidate_id,
                status="proposed",
                fact_id=fact.fact_id,
                fact_status=fact.status,
                error=None,
                db_path=db_path,
            )
            return GovernedFactWriteResult(
                candidate_id=candidate_id,
                fact_id=fact.fact_id,
                fact_status=fact.status,
                candidate_recorded=True,
            )
        except (sqlite3.Error, TypeError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            _update_candidate(
                candidate_id,
                status="failed",
                fact_id=None,
                fact_status=None,
                error=error,
                db_path=db_path,
            )
            return GovernedFactWriteResult(
                candidate_id=candidate_id,
                fact_id=None,
                fact_status=None,
                candidate_recorded=True,
                governance_error=error,
            )

    def shadow_read_diff(
        self,
        *,
        category: str | None = None,
        key: str | None = None,
        scope_filters: dict[str, Any] | None = None,
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Compare legacy entity_state rows with governance facts.

        The report is intentionally explanatory, not a hard cutover gate.  It
        helps Phase A/B dual-write users understand which legacy facts have no
        governed candidate or only quarantined evidence.
        """
        scope = {key_: value_ for key_, value_ in dict(scope_filters or {}).items() if value_ not in (None, "")}
        with closing(get_connection(db_path)) as conn:
            _ensure_candidate_schema(conn)
            legacy = _legacy_rows(conn, category=category, key=key, scope=scope)
            governed = _governed_rows(conn, category=category, key=key, scope=scope)
            candidates = _candidate_rows(conn, category=category, key=key, scope=scope)
        governed_by_key = {(row["subject"], row["predicate"]): row for row in governed}
        candidates_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in candidates:
            candidates_by_key.setdefault((row["category"], row["entity_key"]), []).append(row)
        diffs: list[dict[str, Any]] = []
        for row in legacy:
            row_key = (row["category"], row["entity_key"])
            fact = governed_by_key.get(row_key)
            candidate_rows = candidates_by_key.get(row_key, [])
            if fact is None:
                diffs.append(
                    {
                        "category": row["category"],
                        "entity_key": row["entity_key"],
                        "legacy_value": row["entity_value"],
                        "governance_status": "missing",
                        "candidate_count": len(candidate_rows),
                        "explain": "legacy fact has no governed fact row",
                    }
                )
            elif fact["object"] != row["entity_value"]:
                diffs.append(
                    {
                        "category": row["category"],
                        "entity_key": row["entity_key"],
                        "legacy_value": row["entity_value"],
                        "governed_value": fact["object"],
                        "governance_status": fact["status"],
                        "candidate_count": len(candidate_rows),
                        "explain": "legacy and governed values differ",
                    }
                )
            elif fact["status"] != "active":
                diffs.append(
                    {
                        "category": row["category"],
                        "entity_key": row["entity_key"],
                        "legacy_value": row["entity_value"],
                        "governed_value": fact["object"],
                        "governance_status": fact["status"],
                        "candidate_count": len(candidate_rows),
                        "explain": "governed row exists but is not active",
                    }
                )
        return {
            "legacy_count": len(legacy),
            "governed_count": len(governed),
            "candidate_count": len(candidates),
            "diff_count": len(diffs),
            "diffs": diffs,
        }


def _ensure_candidate_schema(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_fact_candidates (
            candidate_id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            entity_value TEXT NOT NULL,
            reason TEXT,
            source_log_id INTEGER,
            source_media_id INTEGER,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            evidence_text TEXT NOT NULL,
            source_full_text_hash TEXT NOT NULL,
            trust_level INTEGER NOT NULL,
            scope_json TEXT NOT NULL,
            status TEXT NOT NULL,
            fact_id TEXT,
            fact_status TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_governance_fact_candidates_key "
        "ON governance_fact_candidates(category, entity_key, updated_at DESC)"
    )


def _record_candidate(
    *,
    category: str,
    key: str,
    value: str,
    reason: str | None,
    source_log_id: int | None,
    source_media_id: int | None,
    source_type: str,
    source_id: str,
    evidence_text: str,
    source_full_text: str,
    trust_level: int,
    scope: dict[str, Any],
    db_path: str | Path | None,
) -> str:
    now = utc_now()
    candidate_id = f"cand_{uuid.uuid4().hex}"
    with closing(get_connection(db_path)) as conn, conn:
        _ensure_candidate_schema(conn)
        conn.execute(
            """
            INSERT INTO governance_fact_candidates (
                candidate_id, category, entity_key, entity_value, reason,
                source_log_id, source_media_id, source_type, source_id,
                evidence_text, source_full_text_hash, trust_level, scope_json,
                status, fact_id, fact_status, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                category,
                key,
                value,
                reason,
                source_log_id,
                source_media_id,
                source_type,
                source_id,
                evidence_text,
                _text_hash(source_full_text),
                trust_level,
                json.dumps(scope, ensure_ascii=False, sort_keys=True),
                "candidate",
                None,
                None,
                None,
                now,
                now,
            ),
        )
    return candidate_id


def _update_candidate(
    candidate_id: str,
    *,
    status: str,
    fact_id: str | None,
    fact_status: str | None,
    error: str | None,
    db_path: str | Path | None,
) -> None:
    with closing(get_connection(db_path)) as conn, conn:
        _ensure_candidate_schema(conn)
        conn.execute(
            """
            UPDATE governance_fact_candidates
            SET status = ?, fact_id = ?, fact_status = ?, error = ?, updated_at = ?
            WHERE candidate_id = ?
            """,
            (status, fact_id, fact_status, error, utc_now(), candidate_id),
        )


def _memory_log_content(log_id: int, *, db_path: str | Path | None) -> str:
    with closing(get_connection(db_path)) as conn:
        row = conn.execute("SELECT content FROM memory_log WHERE id = ?", (int(log_id),)).fetchone()
    return str(row["content"] or "") if row is not None else ""


def _default_evidence_text(category: str, key: str, value: str) -> str:
    return str(value or "").strip() or f"{category}.{key}"


def _default_trust(value: str, source_text: str) -> int:
    return 5 if value and value in source_text else 1


def _claim_type_for_category(category: str, *, source_text: str, value: str) -> str:
    if not source_text or value not in source_text:
        return ClaimType.INFERENCE
    if category == "user_preferences":
        return ClaimType.PREFERENCE
    if category in {"people_relations", "profile"}:
        return ClaimType.PROFILE
    return ClaimType.PROJECT_FACT


def _text_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _legacy_rows(
    conn: Any,
    *,
    category: str | None,
    key: str | None,
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    clauses = ["COALESCE(archived, 0) = 0"]
    params: list[Any] = []
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if key is not None:
        clauses.append("entity_key = ?")
        params.append(key)
    for field in ("tenant_id", "workspace_id", "visibility"):
        if field in scope:
            clauses.append(f"COALESCE({field}, '') = ?")
            params.append(str(scope[field]))
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM entity_state WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",  # noqa: S608
            params,
        ).fetchall()
    ]


def _governed_rows(
    conn: Any,
    *,
    category: str | None,
    key: str | None,
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if category is not None:
        clauses.append("subject = ?")
        params.append(category)
    if key is not None:
        clauses.append("predicate = ?")
        params.append(key)
    for field in ("tenant_id", "workspace_id", "visibility"):
        if field in scope:
            clauses.append(f"COALESCE({field}, '') = ?")
            params.append(str(scope[field]))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM facts {where} ORDER BY updated_at DESC",  # noqa: S608
            params,
        ).fetchall()
    ]


def _candidate_rows(
    conn: Any,
    *,
    category: str | None,
    key: str | None,
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if key is not None:
        clauses.append("entity_key = ?")
        params.append(key)
    if scope:
        for field, value in scope.items():
            clauses.append(f"json_extract(scope_json, '$.{field}') = ?")
            params.append(str(value))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM governance_fact_candidates {where} ORDER BY updated_at DESC",  # noqa: S608
            params,
        ).fetchall()
    ]
