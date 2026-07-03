"""白盒确定性召回(总纲 §4.5 的机械可执行子集)。

无 embedding、无语义分类器:keywords 经可列举的归一化变体(casefold/去空白/
去千分位/去货币符)对 facts 做 substring 匹配;每个候选按 §4.5.3 权重原值
逐项打分,breakdown 与 why_selected 全量可见。缺失信号(tag_match 等)
如实记 0,不虚构。rejected 事实不参与召回;superseded/expired 可作候选
(带 staleness 罚),供冲突/历史展示,但由编译器决定去向。
"""
from __future__ import annotations

import json
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from .fact_contract import FactContract, FactStatus, utc_now

# §4.5.3 权重原值;tag_match v1 恒 0(词典未建,如实缺席)。
WEIGHTS: dict[str, float] = {
    "exact_entity_match": 0.30,
    "predicate_match": 0.20,
    "evidence_strength": 0.15,
    "recency_or_validity": 0.10,
    "scope_match": 0.10,
    "tag_match": 0.05,
    "source_trust": 0.05,
    "reviewer_status": 0.05,
    "conflict_penalty": 0.30,
    "staleness_penalty": 0.20,
    "sensitivity_penalty": 0.20,
}

# 千分位/货币符 + 连字符/下划线(事实 key 规范化会把 - 转 _,匹配侧折叠两者)。
_STRIP_CHARS = "$¥€,-_"
_SENSITIVE_LEVELS = {"personal", "confidential", "secret"}


def _norm(text: str) -> str:
    """归一化(变体白盒可列举):casefold + 去空白 + 去 [,$¥€-_]。"""
    lowered = text.casefold()
    return "".join(ch for ch in lowered if not ch.isspace() and ch not in _STRIP_CHARS)


@dataclass(frozen=True)
class RetrievalPlan:
    """一次召回的完整计划(进 retrieval_runs.plan_json,可回放)。"""

    trace_id: str
    keywords: tuple[str, ...]
    variants: dict[str, str]  # keyword → 归一化形
    filters: dict[str, Any]
    classifier: str
    weights: dict[str, float]

    def to_json(self) -> str:
        return json.dumps(
            {
                "trace_id": self.trace_id,
                "keywords": list(self.keywords),
                "variants": self.variants,
                "filters": self.filters,
                "classifier": self.classifier,
                "weights": self.weights,
                "normalization": "casefold + strip whitespace + strip [,$¥€-_]",
            },
            ensure_ascii=False,
            sort_keys=True,
        )


@dataclass(frozen=True)
class ScoredCandidate:
    """带可解释打分的候选事实。"""

    fact: FactContract
    score: float
    breakdown: dict[str, float]
    why_selected: list[str]
    has_located_span: bool
    matched_keywords: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact.fact_id,
            "status": self.fact.status,
            "claim": f"{self.fact.subject}.{self.fact.predicate} = {self.fact.object_value}",
            "score": round(self.score, 4),
            "score_breakdown": self.breakdown,
            "why_selected": self.why_selected,
            "has_located_span": self.has_located_span,
        }


def retrieve_facts(
    keywords: list[str],
    *,
    entity_id: str | None = None,
    db_path: str | Path | None = None,
) -> tuple[RetrievalPlan, list[ScoredCandidate]]:
    """确定性召回:返回 (计划, score 降序候选);同分按 fact_id 升序(确定并列裁决)。"""
    cleaned = [kw for kw in keywords if kw and kw.strip()]
    plan = RetrievalPlan(
        trace_id=f"tr_{uuid.uuid4().hex}",
        keywords=tuple(cleaned),
        variants={kw: _norm(kw) for kw in cleaned},
        filters={"entity_id": entity_id} if entity_id else {},
        classifier="none.v1",
        weights=dict(WEIGHTS),
    )
    now = utc_now()
    candidates: list[ScoredCandidate] = []
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM facts WHERE status != 'rejected'"
        params: list[Any] = []
        if entity_id is not None:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        for row in cursor.execute(sql, params).fetchall():
            fact = FactContract.from_row(row)
            hits = _match(fact, plan.variants)
            if not hits:
                continue
            candidates.append(_score(cursor, fact, hits, entity_id=entity_id, now=now))
    candidates.sort(key=lambda c: (-c.score, c.fact.fact_id))
    return plan, candidates


def _match(fact: FactContract, variants: dict[str, str]) -> list[tuple[str, str]]:
    """返回命中列表 [(keyword, 命中列名)];一个 keyword 只记最强命中列。"""
    fields = (
        ("entity_id", _norm(fact.entity_id)),
        ("subject", _norm(fact.subject)),
        ("predicate", _norm(fact.predicate)),
        ("object", _norm(fact.object_value)),
    )
    hits: list[tuple[str, str]] = []
    for keyword, variant in variants.items():
        if not variant:
            continue
        for column, normalized in fields:
            if variant in normalized:
                hits.append((keyword, column))
                break
    return hits


def _score(
    cursor: Any,
    fact: FactContract,
    hits: list[tuple[str, str]],
    *,
    entity_id: str | None,
    now: str,
) -> ScoredCandidate:
    breakdown = dict.fromkeys(WEIGHTS, 0.0)
    why: list[str] = []

    for keyword, column in hits:
        variant = _norm(keyword)
        if column in ("entity_id", "subject"):
            exact = variant in (_norm(fact.entity_id), _norm(fact.subject))
            value = 1.0 if exact else 0.5
            breakdown["exact_entity_match"] = max(breakdown["exact_entity_match"], value)
            why.append(f"关键词 '{keyword}' 命中 {column}({'完全' if value == 1.0 else '子串'}匹配)")
        elif column == "predicate":
            breakdown["predicate_match"] = max(breakdown["predicate_match"], 1.0)
            why.append(f"关键词 '{keyword}' 命中 predicate({fact.predicate})")
        else:
            breakdown["predicate_match"] = max(breakdown["predicate_match"], 0.8)
            why.append(f"关键词 '{keyword}' 命中值(object,记入 predicate_match=0.8)")

    located_trust, any_trust = _trust_levels(cursor, fact.fact_id)
    breakdown["evidence_strength"] = located_trust / 5.0
    breakdown["source_trust"] = any_trust / 5.0
    if located_trust:
        why.append(f"已定位证据,信任等级 E{located_trust}")

    valid = fact.status == FactStatus.ACTIVE and (fact.valid_to is None or fact.valid_to >= now)
    breakdown["recency_or_validity"] = 1.0 if valid else 0.0
    if valid:
        why.append("状态 active 且在有效期")

    if entity_id is not None and fact.entity_id == entity_id:
        breakdown["scope_match"] = 1.0
        why.append(f"命中 entity 过滤 {entity_id}")

    if _has_approve(cursor, fact.fact_id):
        breakdown["reviewer_status"] = 1.0
        why.append("经人工 approve")

    if _has_conflict_edge(cursor, fact.fact_id):
        breakdown["conflict_penalty"] = 1.0
        why.append("存在 conflicts_with 冲突边(扣分,详见 Conflicts 节)")

    stale = fact.status in (FactStatus.SUPERSEDED, FactStatus.EXPIRED) or (
        fact.valid_to is not None and fact.valid_to < now
    )
    if stale:
        breakdown["staleness_penalty"] = 1.0
        why.append(f"已过时(状态 {fact.status}/valid_to {fact.valid_to})(扣分)")

    if fact.sensitivity in _SENSITIVE_LEVELS:
        breakdown["sensitivity_penalty"] = 1.0
        why.append(f"敏感级 {fact.sensitivity}(扣分)")

    score = sum(
        (WEIGHTS[key] * value) * (-1.0 if key.endswith("_penalty") else 1.0)
        for key, value in breakdown.items()
    )
    return ScoredCandidate(
        fact=fact,
        score=score,
        breakdown=breakdown,
        why_selected=why,
        has_located_span=located_trust > 0,
        matched_keywords=tuple(dict.fromkeys(keyword for keyword, _ in hits)),
    )


def _trust_levels(cursor: Any, fact_id: str) -> tuple[int, int]:
    """(已定位 span 的最高 trust, 任意证据最高 trust);无证据为 (0, 0)。"""
    row = cursor.execute(
        """
        SELECT
            MAX(CASE WHEN es.span_start IS NOT NULL THEN es.trust_level END) AS located,
            MAX(es.trust_level) AS any_trust
        FROM evidence_spans es
        JOIN fact_evidence fe ON fe.evidence_id = es.evidence_id
        WHERE fe.fact_id = ?
        """,
        (fact_id,),
    ).fetchone()
    located = int(row["located"]) if row and row["located"] is not None else 0
    any_trust = int(row["any_trust"]) if row and row["any_trust"] is not None else 0
    return located, any_trust


def _has_approve(cursor: Any, fact_id: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM review_actions WHERE fact_id = ? AND action = 'approve' LIMIT 1",
        (fact_id,),
    ).fetchone()
    return row is not None


def _has_conflict_edge(cursor: Any, fact_id: str) -> bool:
    row = cursor.execute(
        """
        SELECT 1 FROM fact_edges
        WHERE edge_type = 'conflicts_with' AND (from_fact_id = ? OR to_fact_id = ?)
        LIMIT 1
        """,
        (fact_id, fact_id),
    ).fetchone()
    return row is not None
