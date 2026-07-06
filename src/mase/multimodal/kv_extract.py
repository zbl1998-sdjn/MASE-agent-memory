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
_LABEL_MAX_CHARS = 16  # 多段切分时,冒号左侧标签 run 的最大长度(超长=歧义)
# 至少一个字母/CJK(排除纯数字"键":时间 10:30、比例 1:2 等不是标签)。
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_STRIP_FOR_DEDUP = " \t\r\n,.$¥€:：-_/()（）"
# 标签 run 的边界:空白/竖线/常见标点/另一个冒号。
_LABEL_BOUNDARY = set(" \t|、。;;,,()()[]【】《》\"':：")


def _split_first_colon(line: str) -> tuple[str, str] | None:
    """在首个冒号(半角 : / 全角 :)处切;URL scheme 冒号(后跟 //)不算分隔。"""
    for i, ch in enumerate(line):
        if ch in ":：":
            if line[i + 1 : i + 3] == "//":
                continue  # http:// 之类,scheme 冒号跳过
            return line[:i], line[i + 1 :]
    return None


def _label_span(line: str, colon: int) -> tuple[int, str] | None:
    """冒号左侧的标签 run(先跳空白;边界=空白/标点;无边界的超长 run 视为歧义)。"""
    j = colon
    while j > 0 and line[j - 1] in " \t":
        j -= 1
    start = j
    while start > 0 and line[start - 1] not in _LABEL_BOUNDARY:
        start -= 1
        if j - start > _LABEL_MAX_CHARS:
            return None
    label = line[start:j]
    if not label or not _HAS_LETTER.search(label):
        return None  # 空标签或纯数字(时间/比例)不是 KV 分隔
    return start, label


def _split_multi_kv(line: str) -> list[tuple[str, str]] | None:
    """一行含 ≥2 个有效 键:值 段时逐段切分;不足 2 段返回 None(走首冒号老路)。

    每段的值 = 冒号后到下一个有效标签起点的原文切片(逐字);首段的键沿用
    v6 语义(行首到首冒号),不丢多词前缀。无效冒号(纯数字/歧义标签/URL)
    不作边界,其文本留在前一段的值里。
    """
    spans: list[tuple[int, tuple[int, str]]] = []
    for i, ch in enumerate(line):
        if ch not in ":：" or line[i + 1 : i + 3] == "//":
            continue
        span = _label_span(line, i)
        if span is not None:
            spans.append((i, span))
    if len(spans) < 2:
        return None
    pairs: list[tuple[str, str]] = []
    for idx, (colon, (_label_start, label)) in enumerate(spans):
        if idx == 0:
            prefix = line[:colon].strip()
            if prefix and len(prefix) <= _KEY_MAX_CHARS:
                label = prefix
        value_end = spans[idx + 1][1][0] if idx + 1 < len(spans) else len(line)
        value = line[colon + 1 : value_end].strip()
        if label and value:
            pairs.append((label, value))
    return pairs or None


def parse_kv_lines(full_text: str) -> list[CandidateFact]:
    """从底稿逐行确定性抽 键:值 事实;无冒号结构不产出。"""
    facts: list[CandidateFact] = []
    seen: set[tuple[str, str]] = set()

    def _emit(key: str, value: str, line: str) -> None:
        key = key.strip()
        value = value.strip()
        if not key or not value:
            return  # 未填写的表单项(键后无值)不产出
        if len(key) > _KEY_MAX_CHARS:
            return  # 整句被误当键;值仍可能被 LLM 抽到,不在此兜底
        if not _HAS_LETTER.search(key):
            return  # 纯数字键 = 时间/比例,不是标签
        norm_key = re.sub(r"\s+", "_", key)
        dedup = (norm_key, value)
        if dedup in seen:
            return
        seen.add(dedup)
        facts.append(CandidateFact(
            category="general_facts",
            key=norm_key,
            value=value,
            confidence=0.7,  # 规则抽取尽力值;逐字来自底稿
            evidence=line,
        ))

    for raw_line in full_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        multi = _split_multi_kv(line)
        if multi is not None:
            for key, value in multi:
                _emit(key, value, line)
            continue
        split = _split_first_colon(line)
        if split is None:
            continue
        _emit(split[0], split[1], line)
    return facts


def _norm_value(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch not in _STRIP_FOR_DEDUP)


def union_kv_facts(
    llm_facts: list[CandidateFact], kv_facts: list[CandidateFact]
) -> list[CandidateFact]:
    """单向并集:规则事实只在其值已被某 LLM 事实值覆盖(归一化子串)时丢弃。

    v6 用双向子串去重,诊断集逐例取证发现真实反例:LLM 抽了地址中的
    机构短名,KV 行的完整地址值因"包含该短名"被当作重复丢弃——超集
    往往携带新信息(前缀/后缀锚串),因此只有"候选 ⊆ 现有"才不存。
    """
    existing = [_norm_value(f.value) for f in llm_facts if f.value.strip()]
    merged = list(llm_facts)
    for kv in kv_facts:
        nv = _norm_value(kv.value)
        if not nv:
            continue
        if any(nv in ev for ev in existing):
            continue
        merged.append(kv)
        existing.append(nv)
    return merged
