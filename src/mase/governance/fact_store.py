"""facts 四表的唯一写入口;状态机在此强制。

不变式:任何 API 路径都无法产生"active 且无 evidence(或 span 为 NULL)"的事实——
active 只能经 propose_fact 且机械定位成功才发生;定位失败/inference 一律 quarantined
(证据仍留痕供 review,这本身是质量信号)。同键新事实自动 supersede 旧 active 并记
fact_edges 版本链;撤回理由留痕在 confidence_basis_json(review_actions 表留 P1)。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from .admission_gate import (
    QUARANTINE,
    REJECT,
    GateDecision,
    apply_ttl_policy,
    check_structurable,
    scan_sensitive,
)
from .evidence_binder import EXCERPT_MAX_CHARS, build_span
from .fact_contract import (
    ClaimType,
    EvidenceSpan,
    FactContract,
    FactStatus,
    new_evidence_id,
    utc_now,
)

_FACT_INSERT = """
    INSERT INTO facts (
        fact_id, entity_id, claim_type, subject, predicate, object,
        qualifiers_json, status, confidence, confidence_basis_json,
        valid_from, valid_to, observed_at, visibility, sensitivity,
        schema_version, tenant_id, workspace_id, created_at, updated_at
    ) VALUES (
        :fact_id, :entity_id, :claim_type, :subject, :predicate, :object,
        :qualifiers_json, :status, :confidence, :confidence_basis_json,
        :valid_from, :valid_to, :observed_at, :visibility, :sensitivity,
        :schema_version, :tenant_id, :workspace_id, :created_at, :updated_at
    )
"""

_SPAN_INSERT = """
    INSERT INTO evidence_spans (
        evidence_id, source_type, source_id, span_start, span_end,
        quote_hash, quote_excerpt, trust_level, created_at
    ) VALUES (
        :evidence_id, :source_type, :source_id, :span_start, :span_end,
        :quote_hash, :quote_excerpt, :trust_level, :created_at
    )
"""


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _scope_of(qualifiers_json: str | None) -> str | None:
    """从 qualifiers_json 提取 scope(同键判定的组成部分)。"""
    if not qualifiers_json:
        return None
    try:
        data = json.loads(qualifiers_json)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and data.get("scope") is not None:
        return str(data["scope"])
    return None


def propose_fact(
    contract: FactContract,
    evidence_text: str,
    *,
    source_type: str,
    source_id: str,
    trust_level: int,
    source_full_text: str,
    db_path: str | Path | None = None,
) -> FactContract:
    """提交候选事实;返回落库后的最终契约(status 由状态机决定,不信任入参)。

    P1 起写入前过准入门控(spec §5 全序):G2 结构 → G3 敏感 → G5 TTL →
    G1 证据定位 → G4 冲突。secret 命中即脱敏,原值不落任何列。
    """
    if contract.claim_type not in ClaimType.ALL:
        raise ValueError(f"未知 claim_type: {contract.claim_type!r}")

    # G5:tool_state 自动 TTL(先于落库,valid_to 随行入库)。
    contract = apply_ttl_policy(contract)

    forced_status: str | None = None
    gate_note: GateDecision | None = None

    # G2:不可结构化 → quarantined。
    g2 = check_structurable(contract)
    if g2.action == QUARANTINE:
        forced_status, gate_note = FactStatus.QUARANTINED, g2

    # G3:secret → rejected + 脱敏(优先级最高,覆盖 G2 判定);PII → personal + 隔离。
    g3 = scan_sensitive(contract.object_value, evidence_text)
    if g3.action == REJECT:
        redacted = f"[REDACTED:{g3.pattern}]"
        contract = replace(contract, object_value=redacted, sensitivity="secret")
        evidence_text = redacted  # 原引文含凭据,同样不落库
        forced_status, gate_note = FactStatus.REJECTED, g3
    elif g3.action == QUARANTINE:
        contract = replace(contract, sensitivity="personal")
        if forced_status is None:
            forced_status, gate_note = FactStatus.QUARANTINED, g3

    if gate_note is not None:
        basis = dict(contract.confidence_basis or {})
        basis["gate"] = {
            "gate": gate_note.gate,
            "action": gate_note.action,
            "reason": gate_note.reason,
            **({"pattern": gate_note.pattern} if gate_note.pattern else {}),
        }
        contract = replace(contract, confidence_basis=basis)

    span = build_span(
        evidence_text,
        source_full_text,
        source_type=source_type,
        source_id=source_id,
        trust_level=trust_level,
    )
    if span is None:
        # 定位失败:证据仍留痕(excerpt=原引用,span NULL,hash=引用文本自身)。
        span = EvidenceSpan(
            evidence_id=new_evidence_id(),
            source_type=source_type,
            source_id=source_id,
            span_start=None,
            span_end=None,
            quote_hash=hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
            quote_excerpt=evidence_text[:EXCERPT_MAX_CHARS],
            trust_level=trust_level,
            created_at=utc_now(),
        )
        target_status = FactStatus.QUARANTINED
    elif contract.claim_type == ClaimType.INFERENCE:
        target_status = FactStatus.QUARANTINED
    else:
        target_status = FactStatus.ACTIVE

    # 门控终态优先:rejected/quarantined 覆盖 binder 的判定(不会放宽,只会收紧)。
    if forced_status is not None:
        target_status = forced_status

    now = utc_now()
    scope = _scope_of(contract.to_row()["qualifiers_json"])

    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()

        existing = _find_duplicate(cursor, contract, scope, span.quote_hash)
        if existing is not None:
            return FactContract.from_row(existing)

        if target_status == FactStatus.ACTIVE:
            for old_id in _same_key_active_ids(cursor, contract, scope):
                cursor.execute(
                    "UPDATE facts SET status = ?, updated_at = ? WHERE fact_id = ?",
                    (FactStatus.SUPERSEDED, now, old_id),
                )
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO fact_edges (from_fact_id, to_fact_id, edge_type, created_at)
                    VALUES (?, ?, 'supersedes', ?)
                    """,
                    (contract.fact_id, old_id, now),
                )

        final = replace(contract, status=target_status, created_at=now, updated_at=now)
        cursor.execute(_FACT_INSERT, final.to_row())
        cursor.execute(_SPAN_INSERT, span.to_row())
        cursor.execute(
            "INSERT INTO fact_evidence (fact_id, evidence_id, role) VALUES (?, ?, 'supports')",
            (final.fact_id, span.evidence_id),
        )
        if target_status == FactStatus.REJECTED and gate_note is not None:
            _record_review_action(
                cursor,
                fact_id=final.fact_id,
                reviewer="system:gate",
                action="security_redact",
                reason=gate_note.reason,
            )
    return final


def _record_review_action(
    cursor: Any, *, fact_id: str, reviewer: str, action: str, reason: str | None
) -> None:
    cursor.execute(
        """
        INSERT INTO review_actions (review_id, fact_id, reviewer, action, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (f"rev_{uuid.uuid4().hex}", fact_id, reviewer, action, reason, utc_now()),
    )


def _find_duplicate(
    cursor: Any, contract: FactContract, scope: str | None, quote_hash: str
) -> Any | None:
    """幂等判定:同键同值且已有同 quote_hash 证据 → 返回既有 facts 行。"""
    rows = cursor.execute(
        """
        SELECT f.* FROM facts f
        JOIN fact_evidence fe ON fe.fact_id = f.fact_id
        JOIN evidence_spans es ON es.evidence_id = fe.evidence_id
        WHERE f.subject = ? AND f.predicate = ? AND f.object = ?
          AND f.tenant_id = ? AND f.workspace_id = ?
          AND f.status IN ('active', 'quarantined')
          AND es.quote_hash = ?
        """,
        (
            contract.subject,
            contract.predicate,
            contract.object_value,
            contract.tenant_id,
            contract.workspace_id,
            quote_hash,
        ),
    ).fetchall()
    for row in rows:
        if _scope_of(row["qualifiers_json"]) == scope:
            return row
    return None


def _same_key_active_ids(
    cursor: Any, contract: FactContract, scope: str | None
) -> list[str]:
    """同 (subject, predicate, scope, tenant, workspace) 的现存 active 事实。"""
    rows = cursor.execute(
        """
        SELECT fact_id, qualifiers_json FROM facts
        WHERE subject = ? AND predicate = ? AND tenant_id = ? AND workspace_id = ?
          AND status = 'active'
        """,
        (contract.subject, contract.predicate, contract.tenant_id, contract.workspace_id),
    ).fetchall()
    return [
        str(row["fact_id"])
        for row in rows
        if _scope_of(row["qualifiers_json"]) == scope
    ]


def retract_fact(fact_id: str, reason: str, *, db_path: str | Path | None = None) -> bool:
    """撤回事实(任意现状 → retracted);理由与时间留痕在 confidence_basis_json。"""
    now = utc_now()
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT confidence_basis_json FROM facts WHERE fact_id = ?", (fact_id,)
        ).fetchone()
        if row is None:
            return False
        basis: dict[str, Any] = {}
        if row["confidence_basis_json"]:
            try:
                loaded = json.loads(row["confidence_basis_json"])
                if isinstance(loaded, dict):
                    basis = loaded
            except json.JSONDecodeError:
                pass
        basis["retract_reason"] = reason
        basis["retracted_at"] = now
        cursor.execute(
            "UPDATE facts SET status = ?, updated_at = ?, confidence_basis_json = ? WHERE fact_id = ?",
            (
                FactStatus.RETRACTED,
                now,
                json.dumps(basis, ensure_ascii=False, sort_keys=True),
                fact_id,
            ),
        )
    return True


def get_fact(
    fact_id: str, *, with_evidence: bool = True, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """取事实详情;with_evidence 时附全部证据行(含 role)。"""
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT * FROM facts WHERE fact_id = ?", (fact_id,)).fetchone()
        if row is None:
            return None
        detail = _row_to_dict(row)
        if with_evidence:
            detail["evidence"] = [
                _row_to_dict(r)
                for r in cursor.execute(
                    """
                    SELECT es.*, fe.role FROM evidence_spans es
                    JOIN fact_evidence fe ON fe.evidence_id = es.evidence_id
                    WHERE fe.fact_id = ?
                    ORDER BY es.created_at, es.evidence_id
                    """,
                    (fact_id,),
                )
            ]
        return detail


def list_facts(
    *,
    entity_id: str | None = None,
    status: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """列事实(可按 entity/status 过滤),新→旧排序。"""
    clauses: list[str] = []
    params: list[Any] = []
    if entity_id is not None:
        clauses.append("entity_id = ?")
        params.append(entity_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM facts {where} ORDER BY updated_at DESC, fact_id",  # noqa: S608 — 子句白名单拼接,值全走参数
            params,
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def supersession_chain(fact_id: str, *, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """回放版本链(新→旧);链上任一点调用返回同一条链。"""
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        # 先沿 supersedes 边走到链头(最新版本)。
        head = fact_id
        seen = {head}
        while True:
            row = cursor.execute(
                "SELECT from_fact_id FROM fact_edges WHERE to_fact_id = ? AND edge_type = 'supersedes'",
                (head,),
            ).fetchone()
            if row is None or row["from_fact_id"] in seen:
                break
            head = str(row["from_fact_id"])
            seen.add(head)
        # 再从链头向旧方向收集。
        chain: list[dict[str, Any]] = []
        current: str | None = head
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            fact_row = cursor.execute(
                "SELECT * FROM facts WHERE fact_id = ?", (current,)
            ).fetchone()
            if fact_row is None:
                break
            chain.append(_row_to_dict(fact_row))
            edge = cursor.execute(
                "SELECT to_fact_id FROM fact_edges WHERE from_fact_id = ? AND edge_type = 'supersedes'",
                (current,),
            ).fetchone()
            current = str(edge["to_fact_id"]) if edge is not None else None
    return chain
