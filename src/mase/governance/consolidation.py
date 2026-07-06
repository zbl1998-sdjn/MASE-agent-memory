"""治理式记忆巩固与遗忘 v1(白盒压缩;设计规范 2026-07-07)。

只压缩已退出治理召回的 supersession 版本链(superseded/expired):摘要是
``ClaimType.DERIVED_SUMMARY`` 的 E2 派生事实,取值轨迹为结构化 JSON,走
``propose_fact`` 唯一写入口——准入门控原样生效(成员值含 PII 时摘要照样
被隔离),同键幂等判定原样生效(同一条链重复巩固返回既有摘要)。摘要用
``scope=consolidation`` 与基础键隔离,绝不顶掉现行 active 值;``consolidates``
边与 ``derived_from`` 证据联结逐成员留痕,成员行一字节不改,retract 摘要即
整体可逆。遗忘 = 留痕撤回(review_actions 记 ``forget``),永不物理删除。
"""
from __future__ import annotations

import json
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from .fact_contract import ClaimType, FactContract, TrustLevel, new_fact_id, utc_now
from .fact_store import propose_fact, retract_fact

CONSOLIDATION_SCOPE = "consolidation"
DEFAULT_MIN_CHAIN = 4
# 派生摘要的置信:多来源一致派生(E2 档语义),低于任何直接观察。
_SUMMARY_CONFIDENCE = 0.6


def _scope_of_row(qualifiers_json: str | None) -> str | None:
    if not qualifiers_json:
        return None
    try:
        data = json.loads(qualifiers_json)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and data.get("scope") is not None:
        return str(data["scope"])
    return None


def find_consolidation_candidates(
    entity_id: str,
    *,
    min_chain: int = DEFAULT_MIN_CHAIN,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """实体下版本链长度达标的 (subject, predicate) 组;只统计已退出召回的行。

    摘要自身(scope=consolidation)不作候选成员——摘要的版本演进由同键
    supersede 机制自然管理,不参与再压缩。
    """
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT subject, predicate, qualifiers_json FROM facts
            WHERE entity_id = ? AND status IN ('superseded', 'expired')
            """,
            (entity_id,),
        ).fetchall()
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        if _scope_of_row(row["qualifiers_json"]) == CONSOLIDATION_SCOPE:
            continue
        key = (str(row["subject"]), str(row["predicate"]))
        counts[key] = counts.get(key, 0) + 1
    return [
        {"subject": subject, "predicate": predicate, "chain_length": n}
        for (subject, predicate), n in sorted(
            counts.items(), key=lambda kv: (-kv[1], kv[0])
        )
        if n >= min_chain
    ]


def consolidate_chain(
    entity_id: str,
    subject: str,
    predicate: str,
    *,
    min_chain: int = DEFAULT_MIN_CHAIN,
    reviewer: str = "system:consolidation",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """把一条键的 superseded/expired 版本链压缩为一条 E2 派生摘要事实。

    成员行一字节不改;链长不足按 skipped 返回,不落任何行。
    """
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT fact_id, object, observed_at, qualifiers_json FROM facts
            WHERE entity_id = ? AND subject = ? AND predicate = ?
              AND status IN ('superseded', 'expired')
            ORDER BY observed_at, created_at
            """,
            (entity_id, subject, predicate),
        ).fetchall()
    members = [
        {"fact_id": str(r["fact_id"]), "object": str(r["object"]), "observed_at": str(r["observed_at"])}
        for r in rows
        if _scope_of_row(r["qualifiers_json"]) != CONSOLIDATION_SCOPE
    ]
    if len(members) < min_chain:
        return {
            "status": "skipped",
            "reason": f"chain_length {len(members)} < min_chain {min_chain}",
            "member_count": len(members),
        }

    trajectory = [{"value": m["object"], "observed_at": m["observed_at"]} for m in members]
    value = json.dumps(trajectory, ensure_ascii=False, sort_keys=True)
    contract = FactContract(
        fact_id=new_fact_id(),
        entity_id=entity_id,
        claim_type=ClaimType.DERIVED_SUMMARY,
        subject=subject,
        predicate=predicate,
        object_value=value,
        confidence=_SUMMARY_CONFIDENCE,
        observed_at=utc_now(),
        qualifiers={
            "scope": CONSOLIDATION_SCOPE,
            "consolidation": {
                "member_count": len(members),
                "window": [members[0]["observed_at"], members[-1]["observed_at"]],
            },
        },
    )
    # 摘要文本自身即证据源:span 机械自定位,quote_hash 锁轨迹内容;
    # 真正的原文溯源由 derived_from 联结指回每条成员的既有 span。
    summary = propose_fact(
        contract,
        value,
        source_type="consolidation",
        source_id=f"{entity_id}:{predicate}",
        trust_level=TrustLevel.E2,
        source_full_text=value,
        db_path=db_path,
    )
    member_ids = [m["fact_id"] for m in members]
    _link_members(summary.fact_id, member_ids, reviewer=reviewer, db_path=db_path)
    return {
        "status": summary.status,
        "summary_fact_id": summary.fact_id,
        "member_ids": member_ids,
        "member_count": len(members),
    }


def _link_members(
    summary_fact_id: str,
    member_ids: list[str],
    *,
    reviewer: str,
    db_path: str | Path | None,
) -> None:
    """consolidates 边 + derived_from 证据联结 + 审计动作;PK 保证重复调用幂等。"""
    now = utc_now()
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        already_linked = cursor.execute(
            "SELECT 1 FROM fact_edges WHERE from_fact_id = ? AND edge_type = 'consolidates' LIMIT 1",
            (summary_fact_id,),
        ).fetchone()
        for member_id in member_ids:
            cursor.execute(
                """
                INSERT OR IGNORE INTO fact_edges (from_fact_id, to_fact_id, edge_type, created_at)
                VALUES (?, ?, 'consolidates', ?)
                """,
                (summary_fact_id, member_id, now),
            )
            for ev in cursor.execute(
                "SELECT evidence_id FROM fact_evidence WHERE fact_id = ? AND role = 'supports'",
                (member_id,),
            ).fetchall():
                cursor.execute(
                    "INSERT OR IGNORE INTO fact_evidence (fact_id, evidence_id, role) VALUES (?, ?, 'derived_from')",
                    (summary_fact_id, str(ev["evidence_id"])),
                )
        if already_linked is None:
            cursor.execute(
                """
                INSERT INTO review_actions (review_id, fact_id, reviewer, action, reason, created_at)
                VALUES (?, ?, ?, 'consolidate', ?, ?)
                """,
                (
                    f"rev_{uuid.uuid4().hex}",
                    summary_fact_id,
                    reviewer,
                    f"consolidated {len(member_ids)} superseded/expired facts",
                    now,
                ),
            )


def forget_fact(
    fact_id: str,
    reason: str,
    *,
    reviewer: str = "user",
    db_path: str | Path | None = None,
) -> bool:
    """可审计的遗忘:撤回召回资格,证据行原样保留,review_actions 记 forget。"""
    if not retract_fact(fact_id, reason, reviewer=None, db_path=db_path):
        return False
    with closing(get_connection(db_path)) as conn, conn:
        conn.execute(
            """
            INSERT INTO review_actions (review_id, fact_id, reviewer, action, reason, created_at)
            VALUES (?, ?, ?, 'forget', ?, ?)
            """,
            (f"rev_{uuid.uuid4().hex}", fact_id, reviewer, reason, utc_now()),
        )
    return True


__all__ = [
    "CONSOLIDATION_SCOPE",
    "DEFAULT_MIN_CHAIN",
    "consolidate_chain",
    "find_consolidation_candidates",
    "forget_fact",
]
