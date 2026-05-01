from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

_CURRENT_STATE_MARKERS = (
    "现在",
    "当前",
    "目前",
    "latest",
    "current",
    "now",
    "是多少",
    "是什么",
    "多少",
)
_TEMPORAL_MARKERS = (
    "上次",
    "之前",
    "此前",
    "当时",
    "昨天",
    "前几天",
    "几周前",
    "上周",
    "上个月",
    "before",
    "previously",
    "earlier",
    "yesterday",
    "last week",
    "last month",
)
_AGGREGATE_MARKERS = (
    "一共",
    "总共",
    "多少次",
    "几次",
    "统计",
    "汇总",
    "列出",
    "全部",
    "how many",
    "count",
    "list all",
    "aggregate",
)
_CROSS_SESSION_MARKERS = (
    "之前聊过",
    "之前几次",
    "多次",
    "跨会话",
    "所有会话",
    "across sessions",
    "multiple sessions",
    "we discussed before",
)
_CONFLICT_MARKERS = (
    "说错",
    "纠正",
    "更正",
    "不是",
    "而是",
    "actually",
    "correction",
    "corrected",
)
_UPDATE_MARKERS = (
    "改成",
    "更新",
    "变成",
    "现在改为",
    "最新改成",
    "changed to",
    "updated to",
    "now set to",
)
_UPDATE_STYLE_MARKERS = (
    "latest",
    "most recent",
    "most recently",
    "currently",
    "initially",
    "at first",
    "when i just started",
    "when i first started",
    "when i first",
    "previously",
    "used to",
)
_PREFERENCE_MARKERS = (
    "喜欢",
    "偏好",
    "最喜欢",
    "习惯",
    "prefer",
    "favorite",
)
_RECOMMENDATION_MARKERS = (
    "recommend",
    "suggest",
    "tips",
    "advice",
    "ideas",
    "what should i",
    "what to look for",
    "what to do",
)
_PROCEDURAL_MARKERS = (
    "流程",
    "步骤",
    "规则",
    "规范",
    "policy",
    "workflow",
    "how do we",
)
_LOW_CONFIDENCE_MARKERS = (
    "那个",
    "这个",
    "那次",
    "那条",
    "这个值",
    "that one",
    "this one",
)
_MARKERS_TO_STRIP = tuple(
    set(
        _TEMPORAL_MARKERS
        + _AGGREGATE_MARKERS
        + _CROSS_SESSION_MARKERS
        + _CONFLICT_MARKERS
        + _UPDATE_MARKERS
        + _LOW_CONFIDENCE_MARKERS
    )
)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _strip_markers(question: str) -> str:
    text = question
    for marker in _MARKERS_TO_STRIP:
        text = re.sub(re.escape(marker), " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[？?！!,，。；;:：]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass(frozen=True)
class ProblemClassification:
    problem_type: str
    signals: tuple[str, ...]
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_type": self.problem_type,
            "signals": list(self.signals),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class RetrievalPlan:
    classification: ProblemClassification
    search_limit: int
    include_history: bool
    use_hybrid_rerank: bool
    use_multipass: bool
    query_variants: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def scope_filters(self) -> dict[str, Any]:
        return {
            "problem_type": self.classification.problem_type,
            "classification_confidence": self.classification.confidence,
            "include_history": self.include_history,
            "use_hybrid_rerank": self.use_hybrid_rerank,
        }

    def to_search_kwargs(self) -> dict[str, Any]:
        return {
            "query_variants": list(self.query_variants),
            "scope_filters": self.scope_filters,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.to_dict(),
            "search_limit": self.search_limit,
            "include_history": self.include_history,
            "use_hybrid_rerank": self.use_hybrid_rerank,
            "use_multipass": self.use_multipass,
            "query_variants": list(self.query_variants),
            "reasons": list(self.reasons),
        }


class ProblemClassifier:
    def classify(self, question: str, route_keywords: list[str] | None = None) -> ProblemClassification:
        lowered = question.lower()
        qtype = str(os.environ.get("MASE_QTYPE") or "").strip().lower()
        recommendation_like = _contains_any(lowered, _RECOMMENDATION_MARKERS)
        signals: list[str] = []
        if _contains_any(lowered, _CONFLICT_MARKERS):
            signals.append("conflict-marker")
        if _contains_any(lowered, _UPDATE_MARKERS):
            signals.append("update-marker")
        if _contains_any(lowered, _UPDATE_STYLE_MARKERS):
            signals.append("update-style-marker")
        if _contains_any(lowered, _TEMPORAL_MARKERS):
            signals.append("temporal-marker")
        if _contains_any(lowered, _AGGREGATE_MARKERS):
            signals.append("aggregate-marker")
        if _contains_any(lowered, _CROSS_SESSION_MARKERS):
            signals.append("cross-session-marker")
        if _contains_any(lowered, _PREFERENCE_MARKERS):
            signals.append("preference-marker")
        if recommendation_like:
            signals.append("recommendation-marker")
        if qtype == "single-session-preference":
            signals.append("qtype-single-session-preference")
        if qtype == "knowledge-update":
            signals.append("qtype-knowledge-update")
        if _contains_any(lowered, _PROCEDURAL_MARKERS):
            signals.append("procedural-marker")
        if _contains_any(lowered, _CURRENT_STATE_MARKERS):
            signals.append("current-state-marker")
        if _contains_any(lowered, _LOW_CONFIDENCE_MARKERS):
            signals.append("low-confidence-marker")
        if route_keywords and any(str(item).strip() for item in route_keywords):
            signals.append("route-keywords-present")

        if _contains_any(lowered, _CONFLICT_MARKERS):
            problem_type = "conflict"
        elif _contains_any(lowered, _UPDATE_MARKERS):
            problem_type = "update"
        elif _contains_any(lowered, _CROSS_SESSION_MARKERS):
            problem_type = "cross_session"
        elif _contains_any(lowered, _AGGREGATE_MARKERS):
            problem_type = "aggregate"
        elif _contains_any(lowered, _TEMPORAL_MARKERS):
            problem_type = "temporal"
        elif qtype == "knowledge-update":
            problem_type = "update"
        elif qtype == "single-session-preference":
            problem_type = "preference"
        elif _contains_any(lowered, _PREFERENCE_MARKERS) or recommendation_like:
            problem_type = "preference"
        elif _contains_any(lowered, _PROCEDURAL_MARKERS):
            problem_type = "procedural"
        elif _contains_any(lowered, _CURRENT_STATE_MARKERS):
            problem_type = "current_state"
        elif _contains_any(lowered, _LOW_CONFIDENCE_MARKERS):
            problem_type = "low_confidence"
        else:
            problem_type = "general_recall"

        confidence = "high" if len(signals) >= 2 else "medium" if signals else "low"
        return ProblemClassification(problem_type=problem_type, signals=tuple(signals), confidence=confidence)


def build_retrieval_plan(
    question: str,
    *,
    route_keywords: list[str] | None = None,
    base_limit: int = 5,
) -> RetrievalPlan:
    classification = ProblemClassifier().classify(question, route_keywords=route_keywords)
    qtype = str(os.environ.get("MASE_QTYPE") or "").strip().lower()
    search_limit = max(1, int(base_limit or 5))
    include_history = False
    use_hybrid_rerank = False
    use_multipass = False
    reasons: list[str] = [classification.problem_type]
    query_variants: list[str] = []

    if classification.problem_type in {"conflict", "update"}:
        include_history = True
        search_limit = max(search_limit, 8)
        reasons.append("include-fact-history")
    elif (
        classification.problem_type in {"current_state", "aggregate", "general_recall", "low_confidence"}
        and _contains_any(question, _UPDATE_STYLE_MARKERS)
    ):
        include_history = True
        search_limit = max(search_limit, 8)
        reasons.extend(["facts-first-priority", "include-fact-history"])
    elif classification.problem_type == "temporal":
        include_history = True
        use_hybrid_rerank = True
        search_limit = max(search_limit, 8)
        reasons.extend(["temporal-window", "temporal-rerank"])
    elif classification.problem_type in {"aggregate", "cross_session"}:
        use_hybrid_rerank = True
        search_limit = max(search_limit, 10)
        reasons.extend(["widen-search", "hybrid-rerank"])
    elif classification.problem_type == "low_confidence":
        use_hybrid_rerank = True
        search_limit = max(search_limit, 8)
        reasons.extend(["ambiguous-reference", "hybrid-rerank"])
    elif classification.problem_type == "preference":
        search_limit = max(search_limit, 10 if qtype == "single-session-preference" else 6)
        use_hybrid_rerank = True
        reasons.extend(["preference-profile", "hybrid-rerank"])
        if "__FULL_QUERY__" not in query_variants:
            query_variants.append("__FULL_QUERY__")
    elif classification.problem_type == "procedural":
        search_limit = max(search_limit, 6)
        reasons.append("slight-widening")
    elif classification.problem_type == "current_state":
        reasons.append("facts-first-priority")

    stripped = _strip_markers(question)
    if stripped and stripped != question and len(stripped) >= 3:
        query_variants.append(stripped)
    if route_keywords:
        joined = " ".join(str(item).strip() for item in route_keywords if str(item).strip())
        if joined and joined not in query_variants and joined != question:
            query_variants.append(joined)

    return RetrievalPlan(
        classification=classification,
        search_limit=search_limit,
        include_history=include_history,
        use_hybrid_rerank=use_hybrid_rerank,
        use_multipass=use_multipass,
        query_variants=tuple(query_variants[:3]),
        reasons=tuple(reasons),
    )


__all__ = [
    "ProblemClassification",
    "ProblemClassifier",
    "RetrievalPlan",
    "build_retrieval_plan",
]
