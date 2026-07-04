"""确定性 键:值 行解析(与 doc_facts LLM 抽取取并集)。

半结构化表单/收据的 ``键<冒号>值`` 行用纯代码规则解析:值逐字取自底稿,
不推测、不改写(evidence=整行,治理层 span 定位天然通过);无冒号结构的
装饰页/口号行不产出 → 幻觉零风险。这是补 LLM 单次枚举遗漏的确定性兜底
(dev 取证:漏抽多为"底稿已有但没被枚举到")。规则通用,不引用任何评测内容。
"""
from __future__ import annotations

import re

from .extractor import CandidateFact

_KEY_MAX_CHARS = 60
# 至少一个字母/CJK(排除纯数字"键":时间 10:30、比例 1:2 等不是标签)。
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_STRIP_FOR_DEDUP = " \t\r\n,.$¥€:：-_/()（）"


def _split_first_colon(line: str) -> tuple[str, str] | None:
    """在首个冒号(半角 : / 全角 :)处切;URL scheme 冒号(后跟 //)不算分隔。"""
    for i, ch in enumerate(line):
        if ch in ":：":
            if line[i + 1 : i + 3] == "//":
                continue  # http:// 之类,scheme 冒号跳过
            return line[:i], line[i + 1 :]
    return None


def parse_kv_lines(full_text: str) -> list[CandidateFact]:
    """从底稿逐行确定性抽 键:值 事实;无冒号结构不产出。"""
    facts: list[CandidateFact] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in full_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        split = _split_first_colon(line)
        if split is None:
            continue
        key = split[0].strip()
        value = split[1].strip()
        if not key or not value:
            continue  # 未填写的表单项(键后无值)不产出
        if len(key) > _KEY_MAX_CHARS:
            continue  # 整句被误当键;值仍可能被 LLM 抽到,不在此兜底
        if not _HAS_LETTER.search(key):
            continue  # 纯数字键 = 时间/比例,不是标签
        norm_key = re.sub(r"\s+", "_", key)
        dedup = (norm_key, value)
        if dedup in seen:
            continue
        seen.add(dedup)
        facts.append(CandidateFact(
            category="general_facts",
            key=norm_key,
            value=value,
            confidence=0.7,  # 规则抽取尽力值;逐字来自底稿
            evidence=line,
        ))
    return facts


def _norm_value(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch not in _STRIP_FOR_DEDUP)


def union_kv_facts(
    llm_facts: list[CandidateFact], kv_facts: list[CandidateFact]
) -> list[CandidateFact]:
    """并集:规则事实只在其值未与任一 LLM 事实值重叠时加入(避免重复存值)。

    重叠判定为归一化后的双向子串——LLM 已覆盖该值(或其超集)则不重复存。
    """
    existing = [_norm_value(f.value) for f in llm_facts if f.value.strip()]
    merged = list(llm_facts)
    for kv in kv_facts:
        nv = _norm_value(kv.value)
        if not nv:
            continue
        if any(nv in ev or ev in nv for ev in existing):
            continue
        merged.append(kv)
        existing.append(nv)
    return merged
