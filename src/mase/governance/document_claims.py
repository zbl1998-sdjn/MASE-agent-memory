"""Document claim memory utilities(P5):claim sheet, grounding QA, stale marking.

文档事实已经由多模态摄取写入 `ClaimType.DOCUMENT_CLAIM`。本模块不另建真源,
只把 facts/evidence_spans/media_extraction 串成可审计的文档 claim 视图。
"""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from .fact_contract import ClaimType, FactStatus, utc_now


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _load_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def list_document_claims(
    *,
    entity_id: str | None = None,
    status: str | None = None,
    source_id: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """列出 document_claim 事实,带 checksum/version/span/chunk 证据映射。"""
    clauses = ["f.claim_type = ?"]
    params: list[Any] = [ClaimType.DOCUMENT_CLAIM]
    if entity_id is not None:
        clauses.append("f.entity_id = ?")
        params.append(entity_id)
    if status is not None:
        clauses.append("f.status = ?")
        params.append(status)
    if source_id is not None:
        clauses.append("es.source_id = ?")
        params.append(source_id)
    where = " AND ".join(clauses)
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        rows = cursor.execute(
            f"""
            SELECT
                f.*,
                es.evidence_id,
                es.source_type,
                es.source_id,
                es.span_start,
                es.span_end,
                es.quote_hash,
                es.quote_excerpt,
                es.trust_level,
                es.created_at AS evidence_created_at,
                fe.role
            FROM facts f
            LEFT JOIN fact_evidence fe ON fe.fact_id = f.fact_id
            LEFT JOIN evidence_spans es ON es.evidence_id = fe.evidence_id
            WHERE {where}
            ORDER BY f.updated_at DESC, f.fact_id, es.created_at
            """,  # noqa: S608 - where 子句由固定白名单拼接
            params,
        ).fetchall()
        claims: dict[str, dict[str, Any]] = {}
        for row in rows:
            fact_id = str(row["fact_id"])
            if fact_id not in claims:
                fact = _row_to_dict(row)
                qualifiers = _load_json_object(fact.get("qualifiers_json"))
                basis = _load_json_object(fact.get("confidence_basis_json"))
                metadata = _document_metadata(
                    cursor,
                    source_type=fact.get("source_type"),
                    source_id=fact.get("source_id"),
                    entity_id=str(fact.get("entity_id") or ""),
                )
                claims[fact_id] = {
                    "fact_id": fact_id,
                    "entity_id": fact["entity_id"],
                    "claim_type": fact["claim_type"],
                    "subject": fact["subject"],
                    "predicate": fact["predicate"],
                    "object": fact["object"],
                    "status": fact["status"],
                    "confidence": fact["confidence"],
                    "document_checksum": metadata["document_checksum"],
                    "document_version": metadata["document_version"],
                    "source_uri": metadata.get("source_uri") or qualifiers.get("scope"),
                    "page": qualifiers.get("page"),
                    "is_stale": "document_stale" in basis or fact["status"] == FactStatus.EXPIRED,
                    "stale_reason": (basis.get("document_stale") or {}).get("reason")
                    if isinstance(basis.get("document_stale"), dict)
                    else None,
                    "evidence": [],
                }
            if row["evidence_id"] is not None:
                claims[fact_id]["evidence"].append(
                    _evidence_view(
                        cursor,
                        source_type=row["source_type"],
                        source_id=row["source_id"],
                        span_start=row["span_start"],
                        span_end=row["span_end"],
                        evidence_id=row["evidence_id"],
                        quote_hash=row["quote_hash"],
                        quote_excerpt=row["quote_excerpt"],
                        trust_level=row["trust_level"],
                    )
                )
        return list(claims.values())


def render_document_claim_sheet(
    *,
    entity_id: str | None = None,
    status: str | None = None,
    db_path: str | Path | None = None,
) -> str:
    """导出人工可读 document claim fact sheet(Markdown)。"""
    claims = list_document_claims(entity_id=entity_id, status=status, db_path=db_path)
    lines = [
        "# Document Claim Fact Sheet",
        "",
        f"- entity_id: {entity_id or '*'}",
        f"- status: {status or '*'}",
        f"- claim_count: {len(claims)}",
        "",
        "| fact_id | status | claim | source | chunk | quote |",
        "|---|---|---|---|---|---|",
    ]
    for claim in claims:
        evidence = claim["evidence"][0] if claim["evidence"] else {}
        claim_text = f"{claim['subject']}.{claim['predicate']} = {claim['object']}"
        source = str(claim.get("source_uri") or evidence.get("source_ref") or "")
        chunk = str(evidence.get("chunk_ref") or "")
        quote = str(evidence.get("quote_excerpt") or "")
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    claim["fact_id"],
                    claim["status"],
                    claim_text,
                    source,
                    chunk,
                    quote,
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def evaluate_document_claims(
    *,
    entity_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """文档 QA 口径:检查 claim 是否有可回指 chunk/span 的证据。"""
    claims = list_document_claims(entity_id=entity_id, db_path=db_path)
    by_status: dict[str, int] = {}
    missing_refs: list[str] = []
    for claim in claims:
        by_status[str(claim["status"])] = by_status.get(str(claim["status"]), 0) + 1
        evidence = claim["evidence"]
        if not any(item.get("span_start") is not None and item.get("span_end") is not None for item in evidence):
            missing_refs.append(str(claim["fact_id"]))
    claim_count = len(claims)
    located_count = claim_count - len(missing_refs)
    return {
        "entity_id": entity_id,
        "claim_count": claim_count,
        "located_count": located_count,
        "missing_located_span_count": len(missing_refs),
        "missing_located_span_fact_ids": missing_refs,
        "by_status": by_status,
        "grounding_rate": (located_count / claim_count) if claim_count else 1.0,
    }


def mark_document_claims_stale(
    *,
    source_id: str | None = None,
    document_checksum: str | None = None,
    source_uri: str | None = None,
    reason: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """文档版本更新后,把旧 active document_claim 标记为 expired/stale。"""
    if not any((source_id, document_checksum, source_uri)):
        raise ValueError("source_id/document_checksum/source_uri 至少提供一个")
    now = utc_now()
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        clauses = ["f.claim_type = ?", "f.status = ?"]
        params: list[Any] = [ClaimType.DOCUMENT_CLAIM, FactStatus.ACTIVE]
        selector_parts: list[str] = []
        if source_id is not None:
            selector_parts.append("es.source_id = ?")
            params.append(source_id)
        if document_checksum is not None:
            selector_parts.append("(ma.sha256 = ? OR f.entity_id = ?)")
            params.extend([document_checksum, f"media:{document_checksum[:12]}"])
        if source_uri is not None:
            selector_parts.append("ma.source_uri = ?")
            params.append(source_uri)
        clauses.append("(" + " OR ".join(selector_parts) + ")")
        rows = cursor.execute(
            f"""
            SELECT DISTINCT f.fact_id, f.confidence_basis_json
            FROM facts f
            JOIN fact_evidence fe ON fe.fact_id = f.fact_id
            JOIN evidence_spans es ON es.evidence_id = fe.evidence_id
            LEFT JOIN media_extraction me
                ON es.source_type = 'media_extraction' AND me.id = CAST(es.source_id AS INTEGER)
            LEFT JOIN media_asset ma ON ma.id = me.media_id
            WHERE {" AND ".join(clauses)}
            """,  # noqa: S608 - clauses are fixed and values are parameterized
            params,
        ).fetchall()
        stale_ids: list[str] = []
        for row in rows:
            basis = _load_json_object(row["confidence_basis_json"])
            basis["document_stale"] = {
                "reason": reason,
                "source_id": source_id,
                "document_checksum": document_checksum,
                "source_uri": source_uri,
                "marked_at": now,
            }
            cursor.execute(
                """
                UPDATE facts
                SET status = ?, valid_to = COALESCE(valid_to, ?), updated_at = ?, confidence_basis_json = ?
                WHERE fact_id = ?
                """,
                (
                    FactStatus.EXPIRED,
                    now,
                    now,
                    json.dumps(basis, ensure_ascii=False, sort_keys=True),
                    row["fact_id"],
                ),
            )
            stale_ids.append(str(row["fact_id"]))
    return {"stale_fact_ids": stale_ids, "stale_count": len(stale_ids), "marked_at": now}


def _document_metadata(
    cursor: Any,
    *,
    source_type: Any,
    source_id: Any,
    entity_id: str,
) -> dict[str, Any]:
    checksum = entity_id.removeprefix("media:") if entity_id.startswith("media:") else entity_id
    metadata: dict[str, Any] = {"document_checksum": checksum or None}
    if source_type == "media_extraction" and str(source_id or "").isdigit():
        row = cursor.execute(
            """
            SELECT ma.sha256, ma.source_uri, ma.page_count, me.created_at, me.full_text
            FROM media_extraction me
            JOIN media_asset ma ON ma.id = me.media_id
            WHERE me.id = ?
            """,
            (int(str(source_id)),),
        ).fetchone()
        if row is not None:
            metadata.update(
                document_checksum=row["sha256"],
                source_uri=row["source_uri"],
                page_count=row["page_count"],
                extraction_created_at=row["created_at"],
                full_text=row["full_text"],
            )
    version_basis = f"{source_type}:{source_id}:{metadata.get('document_checksum') or entity_id}"
    metadata["document_version"] = hashlib.sha256(version_basis.encode("utf-8")).hexdigest()[:16]
    return metadata


def _evidence_view(
    cursor: Any,
    *,
    source_type: Any,
    source_id: Any,
    span_start: Any,
    span_end: Any,
    evidence_id: Any,
    quote_hash: Any,
    quote_excerpt: Any,
    trust_level: Any,
) -> dict[str, Any]:
    source_ref = f"{source_type}:{source_id}"
    chunk_ref = f"{source_ref}[{span_start}:{span_end}]" if span_start is not None and span_end is not None else source_ref
    view = {
        "evidence_id": evidence_id,
        "source_type": source_type,
        "source_id": source_id,
        "source_ref": source_ref,
        "chunk_ref": chunk_ref,
        "span_start": span_start,
        "span_end": span_end,
        "quote_hash": quote_hash,
        "quote_excerpt": quote_excerpt,
        "trust_level": trust_level,
    }
    line_range = _line_range(cursor, source_type=source_type, source_id=source_id, span_start=span_start, span_end=span_end)
    if line_range is not None:
        view["line_start"], view["line_end"] = line_range
    return view


def _line_range(
    cursor: Any,
    *,
    source_type: Any,
    source_id: Any,
    span_start: Any,
    span_end: Any,
) -> tuple[int, int] | None:
    if source_type != "media_extraction" or span_start is None or span_end is None or not str(source_id or "").isdigit():
        return None
    row = cursor.execute(
        "SELECT full_text FROM media_extraction WHERE id = ?",
        (int(str(source_id)),),
    ).fetchone()
    if row is None or row["full_text"] is None:
        return None
    full_text = str(row["full_text"])
    start = int(span_start)
    end = int(span_end)
    return (full_text[:start].count("\n") + 1, full_text[:end].count("\n") + 1)


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")[:240]
