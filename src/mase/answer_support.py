"""把最终回答切成句子，并给每个片段标注证据支持状态。"""
from __future__ import annotations

import re
from typing import Any


def _terms(text: str) -> set[str]:
    """提取用于轻量重叠打分的候选词，忽略纯数字噪声。"""
    return {term.lower() for term in re.findall(r"[\w-]{3,}", text) if not term.isdigit()}


def _sentences(answer: str) -> list[str]:
    """按中英文句末标点切分；无句末标点时把整段作为单个 span。"""
    parts = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", answer) if part.strip()]
    return parts or ([answer.strip()] if answer.strip() else [])


def _evidence_text(row: dict[str, Any]) -> str:
    """把多来源证据行折叠为同一个比较文本。"""
    return " ".join(
        str(row.get(key) or "")
        for key in ("content", "entity_value", "entity_key", "category", "answer_preview", "user_question")
    )


def _best_evidence(sentence: str, evidence_rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    """返回与回答片段词项重叠最高的一条证据及覆盖率。"""
    sentence_terms = _terms(sentence)
    if not sentence_terms:
        return None, 0.0
    best: tuple[dict[str, Any] | None, float] = (None, 0.0)
    for row in evidence_rows:
        evidence_terms = _terms(_evidence_text(row))
        if not evidence_terms:
            continue
        overlap = len(sentence_terms & evidence_terms)
        score = overlap / max(1, len(sentence_terms))
        if score > best[1]:
            best = (row, score)
    return best


def build_answer_support(answer: str, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """构建 Answer Support 视图，用于区分 supported/weak/unsupported/stale。"""
    spans: list[dict[str, Any]] = []
    for index, sentence in enumerate(_sentences(answer)):
        evidence, score = _best_evidence(sentence, evidence_rows)
        stale = bool(evidence and evidence.get("superseded_at"))
        if stale:
            status = "stale"
        elif score >= 0.45:
            status = "supported"
        elif score > 0:
            status = "weak"
        else:
            status = "unsupported"
        spans.append(
            {
                "span_index": index,
                "text": sentence,
                "support_status": status,
                "support_score": round(score, 3),
                "evidence": evidence,
            }
        )
    summary = {
        "span_count": len(spans),
        "supported_count": sum(1 for span in spans if span["support_status"] == "supported"),
        "weak_count": sum(1 for span in spans if span["support_status"] == "weak"),
        "unsupported_count": sum(1 for span in spans if span["support_status"] == "unsupported"),
        "stale_count": sum(1 for span in spans if span["support_status"] == "stale"),
    }
    return {"answer": answer, "summary": summary, "spans": spans}


__all__ = ["build_answer_support"]
