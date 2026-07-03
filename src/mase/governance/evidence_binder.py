"""机械证据定位:把"evidence 必须引用原文"从提示词约定升级为不可绕过的门。

evidence 文本必须能在来源全文中逐字定位:
1. 先精确 substring;
2. 再空白归一化容错(VLM 底稿常见字符间空格/换行伪影),命中后把偏移映射回原文;
3. 不做字符级模糊(编辑距离)——定位失败返回 None,调用方降级 quarantined。
"""
from __future__ import annotations

import hashlib

from .fact_contract import EvidenceSpan, new_evidence_id, utc_now

EXCERPT_MAX_CHARS = 200


def _strip_whitespace_with_map(text: str) -> tuple[str, list[int]]:
    """去掉全部空白字符,同时记录归一化索引 → 原文索引的映射。"""
    chars: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch)
            index_map.append(i)
    return "".join(chars), index_map


def locate_evidence(evidence_text: str, source_full_text: str) -> tuple[int, int] | None:
    """在来源全文中逐字定位引文,返回原文字符偏移 (start, end);找不到返回 None。"""
    if not evidence_text or evidence_text.isspace() or not source_full_text:
        return None
    pos = source_full_text.find(evidence_text)
    if pos != -1:
        return (pos, pos + len(evidence_text))
    normalized_evidence = "".join(ch for ch in evidence_text if not ch.isspace())
    if not normalized_evidence:
        return None
    normalized_source, index_map = _strip_whitespace_with_map(source_full_text)
    pos = normalized_source.find(normalized_evidence)
    if pos == -1:
        return None
    start = index_map[pos]
    end = index_map[pos + len(normalized_evidence) - 1] + 1
    return (start, end)


def build_span(
    evidence_text: str,
    source_full_text: str,
    *,
    source_type: str,
    source_id: str,
    trust_level: int,
) -> EvidenceSpan | None:
    """定位成功产出 EvidenceSpan(quote_hash 为原文命中段 sha256);失败返回 None。"""
    located = locate_evidence(evidence_text, source_full_text)
    if located is None:
        return None
    start, end = located
    matched = source_full_text[start:end]
    return EvidenceSpan(
        evidence_id=new_evidence_id(),
        source_type=source_type,
        source_id=source_id,
        span_start=start,
        span_end=end,
        quote_hash=hashlib.sha256(matched.encode("utf-8")).hexdigest(),
        quote_excerpt=matched[:EXCERPT_MAX_CHARS],
        trust_level=trust_level,
        created_at=utc_now(),
    )
