"""Evidence Pack Compiler(总纲 §4.6):不把记忆碎片直接塞给 LLM,先编译成结构化证据包。

Verified Facts 只收 active 且已定位 span 的事实(编译时机械复验,不信任上游);
冲突双方并列 + warning(C3);未命中 keyword 进 Unknowns;命中的 quarantined
进 Do-Not-Assume(C5)。每次编译落 retrieval_runs + context_packs,trace_id
贯穿,全程可回放。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from .fact_contract import FactStatus, utc_now
from .retrieval import ScoredCandidate, retrieve_facts

ANSWER_RULES = (
    "使用中文。",
    "明确区分事实、建议、推断。",
    "对无证据部分标注为建议或待确认。",
)


@dataclass(frozen=True)
class EvidencePack:
    """结构化证据包(§4.6.1);render_markdown 产出注入用文本。"""

    pack_id: str
    trace_id: str
    question: str
    verified: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    unknowns: tuple[str, ...]
    do_not_assume: tuple[str, ...]
    warnings: tuple[str, ...]
    token_estimate: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "trace_id": self.trace_id,
            "question": self.question,
            "verified": list(self.verified),
            "conflicts": list(self.conflicts),
            "unknowns": list(self.unknowns),
            "do_not_assume": list(self.do_not_assume),
            "warnings": list(self.warnings),
            "token_estimate": self.token_estimate,
            "created_at": self.created_at,
        }


def compile_evidence_pack(
    question: str,
    keywords: list[str],
    *,
    entity_id: str | None = None,
    top_k: int = 8,
    db_path: str | Path | None = None,
) -> EvidencePack:
    """召回 → 选取 → 编译 → 审计落库;返回不可变 EvidencePack。"""
    plan, candidates = retrieve_facts(keywords, entity_id=entity_id, db_path=db_path)
    selected = candidates[:top_k]

    verified: list[dict[str, Any]] = []
    warnings: list[str] = []
    do_not_assume: list[str] = []
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        for candidate in selected:
            fact = candidate.fact
            claim = f"{fact.subject}.{fact.predicate} = {fact.object_value}"
            if fact.status == FactStatus.ACTIVE:
                spans = _located_spans(cursor, fact.fact_id)
                if not spans:
                    warnings.append(
                        f"active 事实 {fact.fact_id} 无已定位证据,拒绝注入(数据完整性警告)"
                    )
                    continue
                if candidate.breakdown.get("recency_or_validity", 0.0) < 1.0:
                    warnings.append(f"active 事实 {fact.fact_id} 已过有效期,拒绝注入")
                    continue
                verified.append(
                    {
                        "fact_id": fact.fact_id,
                        "claim": claim,
                        "confidence": fact.confidence,
                        "evidence_ref": [
                            f"{s['source_type']}:{s['source_id']} [{s['span_start']}:{s['span_end']}]"
                            for s in spans
                        ],
                        "evidence_ids": [s["evidence_id"] for s in spans],
                        "validity": _validity_line(fact.observed_at, fact.valid_to),
                        "score": round(candidate.score, 4),
                        "why_selected": list(candidate.why_selected),
                    }
                )
            elif fact.status == FactStatus.QUARANTINED:
                do_not_assume.append(
                    f"不要把未审核事实当已确认:{claim}(quarantined,待 review)"
                )
                if fact.sensitivity == "secret":
                    do_not_assume.append(f"不得使用敏感内容:{fact.fact_id}(sensitivity=secret)")

        conflicts = _collect_conflicts(cursor, selected)

    covered = {kw for c in candidates for kw in c.matched_keywords}
    unknowns = tuple(
        f"尚无记忆事实覆盖:{kw}" for kw in keywords if kw and kw.strip() and kw not in covered
    )

    pack = EvidencePack(
        pack_id=f"cp_{uuid.uuid4().hex}",
        trace_id=plan.trace_id,
        question=question,
        verified=tuple(verified),
        conflicts=tuple(conflicts),
        unknowns=unknowns,
        do_not_assume=tuple(do_not_assume),
        warnings=tuple(warnings),
        token_estimate=0,
        created_at=utc_now(),
    )
    pack = replace(pack, token_estimate=len(render_markdown(pack)) // 4)
    _persist_audit(pack, plan, candidates, db_path=db_path)
    return pack


def render_markdown(pack: EvidencePack) -> str:
    """§4.6.2 模板:五节 + Answer Rules;token_estimate 不进正文(渲染稳定)。"""
    lines = [
        "# Memory Evidence Pack",
        "",
        "## User Question",
        pack.question,
        "",
        "## Verified Facts",
    ]
    if pack.verified:
        for entry in pack.verified:
            lines.append(
                f"- [fact_id={entry['fact_id']} status=active confidence={entry['confidence']}]"
            )
            lines.append(f"  Claim: {entry['claim']}")
            lines.append(f"  Evidence: {'; '.join(entry['evidence_ref'])}")
            lines.append(f"  Validity: {entry['validity']}")
            lines.append(f"  Why: {'; '.join(entry['why_selected'])}")
    else:
        lines.append("- 无(没有可注入的已验证事实)")
    lines += ["", "## Conflicts"]
    if pack.conflicts:
        for conflict in pack.conflicts:
            lines.append(f"- {conflict['warning']}")
            for side in conflict["sides"]:
                lines.append(f"  - [{side['status']}] {side['claim']} (fact_id={side['fact_id']})")
    else:
        lines.append("- None detected.")
    lines += ["", "## Unknowns"]
    lines += [f"- {u}" for u in pack.unknowns] or ["- None."]
    lines += ["", "## Do Not Assume"]
    lines += [f"- {d}" for d in pack.do_not_assume] or ["- None."]
    if pack.warnings:
        lines += ["", "## Warnings"]
        lines += [f"- {w}" for w in pack.warnings]
    lines += ["", "## Answer Rules"]
    lines += [f"- {rule}" for rule in ANSWER_RULES]
    return "\n".join(lines) + "\n"


def _validity_line(observed_at: str, valid_to: str | None) -> str:
    line = f"active since {observed_at}"
    if valid_to:
        line += f", until {valid_to}"
    return line


def _located_spans(cursor: Any, fact_id: str) -> list[Any]:
    return cursor.execute(
        """
        SELECT es.* FROM evidence_spans es
        JOIN fact_evidence fe ON fe.evidence_id = es.evidence_id
        WHERE fe.fact_id = ? AND es.span_start IS NOT NULL
        ORDER BY es.created_at, es.evidence_id
        """,
        (fact_id,),
    ).fetchall()


def _collect_conflicts(cursor: Any, selected: list[ScoredCandidate]) -> list[dict[str, Any]]:
    """入选事实的 conflicts_with 双方并列(C3);按对去重。"""
    seen_pairs: set[frozenset[str]] = set()
    conflicts: list[dict[str, Any]] = []
    for candidate in selected:
        fact_id = candidate.fact.fact_id
        edges = cursor.execute(
            """
            SELECT from_fact_id, to_fact_id FROM fact_edges
            WHERE edge_type = 'conflicts_with' AND (from_fact_id = ? OR to_fact_id = ?)
            """,
            (fact_id, fact_id),
        ).fetchall()
        for edge in edges:
            pair = frozenset({str(edge["from_fact_id"]), str(edge["to_fact_id"])})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            sides = []
            for side_id in sorted(pair):
                row = cursor.execute(
                    "SELECT fact_id, subject, predicate, object, status FROM facts WHERE fact_id = ?",
                    (side_id,),
                ).fetchone()
                if row is not None:
                    sides.append(
                        {
                            "fact_id": row["fact_id"],
                            "claim": f"{row['subject']}.{row['predicate']} = {row['object']}",
                            "status": row["status"],
                        }
                    )
            conflicts.append(
                {
                    "warning": "同键事实存在未裁决冲突,注入双方供参考,勿单边采信",
                    "sides": sides,
                }
            )
    return conflicts


def _persist_audit(
    pack: EvidencePack,
    plan: Any,
    candidates: list[ScoredCandidate],
    *,
    db_path: str | Path | None,
) -> None:
    now = utc_now()
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO retrieval_runs
                (retrieval_id, trace_id, query, plan_json, candidates_json, selected_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"ret_{uuid.uuid4().hex}",
                pack.trace_id,
                pack.question,
                plan.to_json(),
                json.dumps([c.to_dict() for c in candidates], ensure_ascii=False),
                json.dumps(
                    {
                        "verified_fact_ids": [v["fact_id"] for v in pack.verified],
                        "conflicts": list(pack.conflicts),
                        "warnings": list(pack.warnings),
                    },
                    ensure_ascii=False,
                ),
                now,
            ),
        )
        cursor.execute(
            """
            INSERT INTO context_packs
                (context_pack_id, trace_id, question_hash, fact_ids_json, evidence_ids_json,
                 conflicts_json, unknowns_json, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pack.pack_id,
                pack.trace_id,
                hashlib.sha256(pack.question.encode("utf-8")).hexdigest(),
                json.dumps([v["fact_id"] for v in pack.verified], ensure_ascii=False),
                json.dumps(
                    [eid for v in pack.verified for eid in v["evidence_ids"]], ensure_ascii=False
                ),
                json.dumps(list(pack.conflicts), ensure_ascii=False),
                json.dumps(list(pack.unknowns), ensure_ascii=False),
                pack.token_estimate,
                now,
            ),
        )
