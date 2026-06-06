"""评估拒答是否合理，以及非拒答是否有足够证据支撑。"""
from __future__ import annotations

import re
from typing import Any

from mase.answer_support import build_answer_support

# 覆盖英文和中文常见拒答表达；用于质量诊断，不参与安全策略裁决。
REFUSAL_PATTERNS = [
    r"\bi don'?t know\b",
    r"\bi do not know\b",
    r"\bnot enough (information|evidence)\b",
    r"\bcan'?t determine\b",
    r"\bcannot determine\b",
    r"\bno evidence\b",
    r"不知道",
    r"无法确定",
    r"没有足够",
]


def is_refusal(answer: str) -> bool:
    """判断回答文本是否呈现拒答形态。"""
    text = answer.strip().lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in REFUSAL_PATTERNS)


def build_refusal_quality(answer: str, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """结合 Answer Support 区分过度拒答、合理拒答和无证据回答。"""
    support = build_answer_support(answer, evidence_rows)
    summary = support["summary"]
    has_support = int(summary["supported_count"]) > 0 or int(summary["weak_count"]) > 0
    has_evidence = bool(evidence_rows)
    refusal = is_refusal(answer)
    if refusal and has_evidence:
        classification = "over_refusal"
        severity = "high"
    elif refusal:
        classification = "appropriate_refusal"
        severity = "low"
    elif int(summary["unsupported_count"]) > 0 and not has_support:
        classification = "unsupported_answer"
        severity = "high"
    elif int(summary["unsupported_count"]) > 0:
        classification = "partially_supported_answer"
        severity = "medium"
    else:
        classification = "supported_answer"
        severity = "low"
    return {
        "answer": answer,
        "is_refusal": refusal,
        "classification": classification,
        "severity": severity,
        "support": support,
        "evidence_count": len(evidence_rows),
        "recommended_actions": _recommend(classification),
    }


def _recommend(classification: str) -> list[str]:
    """为每类拒答质量结果给出后续排查动作。"""
    if classification == "over_refusal":
        return ["检查召回证据是否被 executor 忽略", "把支持证据加入 trace/answer support 对照"]
    if classification == "unsupported_answer":
        return ["要求 agent 改为无证据拒答", "创建 repair case 检查错误记忆或错误召回"]
    if classification == "partially_supported_answer":
        return ["拆分 answer spans，补齐 unsupported span 的证据"]
    return ["保留样本作为黄金测试候选"]


__all__ = ["build_refusal_quality", "is_refusal"]
