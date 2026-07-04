"""Answer Claim Verifier(总纲 §4.7 机械可执行子集):让回答可被 fact/evidence 检查。

逐句(与 answer_support 同切分规则)把答案映射到 Evidence Pack:
- 命中 verified 值 → SUPPORTED_BY_MEMORY(带 fact_ids/evidence_ids)
- 命中冲突对的非 active 侧值 → CONFLICTING(答案未显式报告冲突即 violation)
- 命中过时候选值且句中无同键现行值 → STALE(violation)
- 命中隔离候选值 → UNSUPPORTED_MEMORY_CLAIM(violation)
- 其余 → UNTAGGED(只审计记忆声明,不评一般内容)

检出口径是"逐字引用型"记忆声明(归一化 substring,与召回同一套 _norm);
语义改写型漏检是已声明边界(spec §7)。审计强制落 answer_audits 表。
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from .evidence_pack import EvidencePack
from .fact_contract import FactStatus, utc_now
from .retrieval import _norm

SUPPORTED_BY_MEMORY = "SUPPORTED_BY_MEMORY"
CONFLICTING = "CONFLICTING"
STALE = "STALE"
UNSUPPORTED_MEMORY_CLAIM = "UNSUPPORTED_MEMORY_CLAIM"
UNTAGGED = "UNTAGGED"


@dataclass(frozen=True)
class AnswerAudit:
    """一次答案审计的完整结果(spans/violations 均可 JSON 回放)。"""

    audit_id: str
    trace_id: str
    answer: str
    spans: tuple[dict[str, Any], ...]
    violations: tuple[dict[str, Any], ...]
    verdict: str  # pass | revise | refuse
    unknowns: tuple[str, ...]
    created_at: str


def _sentences(answer: str) -> list[str]:
    """中英句末标点切分;与 mase.answer_support 同规则(独立实现,治理层零依赖旧读路径)。"""
    parts = [part.strip() for part in re.split(r"(?<=[.!?。!?])\s*", answer) if part.strip()]
    return parts or ([answer.strip()] if answer.strip() else [])


def verify_answer(
    answer: str, pack: EvidencePack, *, db_path: str | Path | None = None
) -> AnswerAudit:
    """逐句核对答案与 Evidence Pack;审计落库后返回不可变结果。"""
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        verified = _facts_by_ids(cursor, [v["fact_id"] for v in pack.verified])
        candidates = _candidates_from_audit(cursor, pack.trace_id)
        stale = {
            fid: row
            for fid, row in candidates.items()
            if row["status"] in (FactStatus.SUPERSEDED, FactStatus.EXPIRED)
        }
        quarantined = {
            fid: row for fid, row in candidates.items() if row["status"] == FactStatus.QUARANTINED
        }
        conflict_other_side, conflict_all_values = _conflict_sides(cursor, pack)

    verified_values = {fid: _norm(row["object"]) for fid, row in verified.items()}
    verified_by_key = _values_by_key(verified)
    evidence_by_fact = {v["fact_id"]: v.get("evidence_ids", []) for v in pack.verified}

    norm_answer = _norm(answer)

    def _conflict_reported(fact_id: str) -> bool:
        # 显式报告 = 答案含"冲突"字样,或该冲突对的双方值全部呈现。
        if "冲突" in answer:
            return True
        values = conflict_all_values.get(fact_id, ())
        return bool(values) and all(v in norm_answer for v in values)

    spans: list[dict[str, Any]] = []
    for index, sentence in enumerate(_sentences(answer)):
        norm_sentence = _norm(sentence)
        span: dict[str, Any] = {
            "span_index": index,
            "text": sentence,
            "tag": UNTAGGED,
            "fact_ids": [],
            "evidence_ids": [],
            "violation": False,
            "reason": "",
        }
        stale_hits = [
            fid
            for fid, row in stale.items()
            if _norm(row["object"]) in norm_sentence
            and not any(v in norm_sentence for v in verified_by_key.get(_key_of(row), ()))
        ]
        conflict_hits = [
            fid
            for fid, side in conflict_other_side.items()
            if _norm(side["object"]) in norm_sentence
        ]
        quarantine_hits = [
            fid
            for fid, row in quarantined.items()
            if fid not in conflict_other_side and _norm(row["object"]) in norm_sentence
        ]
        supported_hits = [fid for fid, v in verified_values.items() if v and v in norm_sentence]

        if stale_hits:
            replacement = [
                v for fid in stale_hits for v in verified_by_key.get(_key_of(stale[fid]), ())
            ]
            span.update(
                tag=STALE,
                fact_ids=stale_hits,
                violation=True,
                reason="该值来自已过时事实(superseded/expired)"
                + (",现行值另见同键 active 事实" if replacement else ""),
            )
        elif conflict_hits:
            reported = all(_conflict_reported(fid) for fid in conflict_hits)
            span.update(
                tag=CONFLICTING,
                fact_ids=conflict_hits,
                violation=not reported,
                reason="该值属未裁决冲突一方"
                + ("(答案已显式报告冲突)" if reported else ",答案未报告冲突即单边采信"),
            )
        elif quarantine_hits:
            span.update(
                tag=UNSUPPORTED_MEMORY_CLAIM,
                fact_ids=quarantine_hits,
                violation=True,
                reason="该值来自未审核隔离事实,不得当已确认",
            )
        elif supported_hits:
            span.update(
                tag=SUPPORTED_BY_MEMORY,
                fact_ids=supported_hits,
                evidence_ids=[eid for fid in supported_hits for eid in evidence_by_fact.get(fid, [])],
                reason="逐字命中已验证事实值",
            )
        spans.append(span)

    violations = tuple(s for s in spans if s["violation"])
    if not violations:
        verdict = "pass"
    elif not pack.verified:
        # 无任何已验证事实支撑还出现记忆声明违规 → 拒答而非编造。
        verdict = "refuse"
    else:
        # 有 verified 支撑时降级为标注修订(refuse 留给零支撑场景)。
        verdict = "revise"

    audit = AnswerAudit(
        audit_id=f"aud_{uuid.uuid4().hex}",
        trace_id=pack.trace_id,
        answer=answer,
        spans=tuple(spans),
        violations=violations,
        verdict=verdict,
        unknowns=pack.unknowns,
        created_at=utc_now(),
    )
    _persist(audit, db_path=db_path)
    return audit


def revise_answer(audit: AnswerAudit) -> str:
    """低幻觉闭环出口:refuse 输出 unknown 而非编造;revise 逐句显式标注 violation。"""
    if audit.verdict == "refuse":
        lines = ["证据不足,无法就该问题给出可验证回答。"]
        if audit.unknowns:
            lines.append("以下信息未知/无记忆覆盖:")
            lines += [f"- {u}" for u in audit.unknowns]
        for violation in audit.violations:
            lines.append(f"- 检出不可用声明:{violation['reason']}")
        lines.append("")
        lines.append(f"原答案(未通过治理审计,仅供追溯):{audit.answer}")
        return "\n".join(lines)
    revised: list[str] = []
    for span in audit.spans:
        text = span["text"]
        if span["violation"]:
            refs = ",".join(span["fact_ids"])
            text += f"〔MASE治理:{span['reason']};fact_id={refs}〕"
        revised.append(text)
    return "\n".join(revised)


def _key_of(row: Any) -> tuple[str, str]:
    return (str(row["subject"]), str(row["predicate"]))


def _values_by_key(facts: dict[str, Any]) -> dict[tuple[str, str], tuple[str, ...]]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for row in facts.values():
        grouped.setdefault(_key_of(row), []).append(_norm(str(row["object"])))
    return {key: tuple(values) for key, values in grouped.items()}


def _facts_by_ids(cursor: Any, fact_ids: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for fact_id in fact_ids:
        row = cursor.execute(
            "SELECT fact_id, subject, predicate, object, status FROM facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if row is not None:
            result[str(row["fact_id"])] = row
    return result


def _candidates_from_audit(cursor: Any, trace_id: str) -> dict[str, Any]:
    """从 retrieval_runs 回放该 trace 的全部候选(审计表就是回放真源)。"""
    run = cursor.execute(
        "SELECT candidates_json FROM retrieval_runs WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    if run is None:
        return {}
    fact_ids = [c["fact_id"] for c in json.loads(run["candidates_json"])]
    return _facts_by_ids(cursor, fact_ids)


def _conflict_sides(
    cursor: Any, pack: EvidencePack
) -> tuple[dict[str, Any], dict[str, tuple[str, ...]]]:
    """返回 (非 active 冲突侧 fid→行, 该侧 fid→冲突对全部值归一化形)。

    active 侧由 trust 阶梯裁决为现行权威,引用它不算单边;引用非 active 侧
    才需要显式报告冲突(双方值齐或"冲突"字样)。
    """
    other_sides: dict[str, Any] = {}
    all_values: dict[str, tuple[str, ...]] = {}
    for conflict in pack.conflicts:
        rows = []
        for side in conflict["sides"]:
            row = cursor.execute(
                "SELECT fact_id, subject, predicate, object, status FROM facts WHERE fact_id = ?",
                (side["fact_id"],),
            ).fetchone()
            if row is not None:
                rows.append(row)
        pair_values = tuple(_norm(str(row["object"])) for row in rows)
        for row in rows:
            if row["status"] != FactStatus.ACTIVE:
                fid = str(row["fact_id"])
                other_sides[fid] = row
                all_values[fid] = pair_values
    return other_sides, all_values


def _persist(audit: AnswerAudit, *, db_path: str | Path | None) -> None:
    with closing(get_connection(db_path)) as conn, conn:
        conn.execute(
            """
            INSERT INTO answer_audits
                (audit_id, trace_id, answer_hash, spans_json, violations_json, verdict, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit.audit_id,
                audit.trace_id,
                hashlib.sha256(audit.answer.encode("utf-8")).hexdigest(),
                json.dumps(list(audit.spans), ensure_ascii=False),
                json.dumps(list(audit.violations), ensure_ascii=False),
                audit.verdict,
                audit.created_at,
            ),
        )
