"""确定性版面结构解析(表格行/问答行/宽空格对/序号选项组)。

与 kv_extract 同族的第二类确定性兜底,覆盖无冒号的版面结构:
- 表格行打包:``| 标签 | 格 | 格 |`` → 首格作键,其余原文切片作值;
- 问答行配对:``…?`` 问句行 → 紧随的勾选选项行聚合作值;
- 宽空格对:``姓名 孙艺   学号 200652468`` → 逐段拆 标签/值;
- 序号选项组:``妊娠情况 1.未孕√ 2.已孕…`` → 整组枚举原文作值。

值取底稿原文切片(evidence=原文行,治理层 span 定位天然通过);装饰页
无上述结构 → 零产出,不影响 halluc_ok。规则全部是通用版面模式,不引用
任何评测内容(anti-overfit 禁令)。
"""
from __future__ import annotations

import re

from .extractor import CandidateFact

_KEY_MAX_CHARS = 60
_LABEL_MAX_CHARS = 16
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_CHECKBOX_CHARS = set("√☑□■")
_QA_ANSWER_MAX_CHARS = 24
_QA_MAX_OPTION_LINES = 4
_QA_MAX_QUESTION_SKIPS = 2  # 中英双语表单:紧随的外文问句行跳过
_WIDE_SPLIT = re.compile(r" {2,}|\t+")
_CJK_LABEL = re.compile(r"^[一-鿿]{2,6}$")
_ENUM_LINE = re.compile(r"^([一-鿿]{2,8})\s*(1[..、].+)$")
_ENUM_SECOND = re.compile(r"2\s*[..、]")
_OPTION_LINE = re.compile(r"^[0-9A-Za-z][..、].+")
_OPTION_LABEL = re.compile(r"^[一-鿿]{2,8}$")
_MULTILINE_OPTION_MIN = 2
_STRIP_FOR_DEDUP = " \t\r\n,.$¥€:：-_/()（）|"


def _fact(key: str, value: str, evidence: str) -> CandidateFact:
    return CandidateFact(
        category="general_facts",
        key=re.sub(r"\s+", "_", key.strip()),
        value=value.strip(),
        confidence=0.7,  # 规则抽取尽力值;值逐字来自底稿
        evidence=evidence,
    )


def _table_row_fact(line: str) -> CandidateFact | None:
    """表格行打包:首个非空格是短标签时,键=首格,值=该行剩余原文切片。"""
    if "|" not in line:
        return None
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    nonempty = [c for c in cells if c and set(c) - set("-: ")]
    if len(nonempty) < 2:
        return None  # 分隔行(---)或格数不足
    first = nonempty[0]
    if len(first) > _LABEL_MAX_CHARS or not _HAS_LETTER.search(first):
        return None  # 长句首格/纯数字序号列不是标签
    pos = line.find(first)
    value = line[pos + len(first):].strip().strip("|").strip()
    if not value or not (set(value) - set("-:| ")):
        return None
    return _fact(first, value, line.strip())


def _is_question(line: str) -> bool:
    return line.endswith(("?", "？")) and 0 < len(line) <= _KEY_MAX_CHARS


def _is_option_line(line: str) -> bool:
    if not line or len(line) > _QA_ANSWER_MAX_CHARS or _is_question(line):
        return False
    if any(ch in _CHECKBOX_CHARS for ch in line):
        return True
    # 手写体勾选框常被转写成"口":口是 口否
    return "口" in line and ("是" in line or "否" in line)


def _question_answer_facts(lines: list[str]) -> list[CandidateFact]:
    """问句行(…?)配对紧随的勾选选项行;选项行必须带勾选符,装饰页不误配。

    evidence 取"问句行到最后一个选项行"的原文连续切片(含中间被跳过的
    双语问句行),保证能在抽取全文中逐字定位(治理层机械 span 绑定)。
    """
    facts: list[CandidateFact] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not _is_question(line) or "|" in line:
            continue
        j = i + 1
        skips = 0
        while j < len(lines) and skips < _QA_MAX_QUESTION_SKIPS and _is_question(lines[j].strip()):
            j += 1
            skips += 1
        options: list[str] = []
        while (j < len(lines) and len(options) < _QA_MAX_OPTION_LINES
               and _is_option_line(lines[j].strip())):
            options.append(lines[j].strip())
            j += 1
        if not options:
            continue
        key = line.rstrip("?？").strip()
        if not key:
            continue
        value = " ".join(options)
        evidence = "\n".join(lines[i:j])
        facts.append(_fact(key, value, evidence))
    return facts


def _seg_colon_pair(seg: str) -> tuple[str, str] | None:
    for i, ch in enumerate(seg):
        if ch in ":：" and seg[i + 1 : i + 3] != "//":
            key, value = seg[:i].strip(), seg[i + 1 :].strip()
            if key and value and len(key) <= _LABEL_MAX_CHARS and _HAS_LETTER.search(key):
                return key, value
            return None
    return None


def _wide_space_facts(line: str) -> list[CandidateFact]:
    """宽空格(≥2 空格/Tab)分段的行:每段按 冒号 或 "CJK短标签+值" 拆对。"""
    if "|" in line:
        return []
    segments = [s.strip() for s in _WIDE_SPLIT.split(line) if s.strip()]
    if len(segments) < 2:
        return []
    facts: list[CandidateFact] = []
    for seg in segments:
        pair = _seg_colon_pair(seg)
        if pair is not None:
            facts.append(_fact(pair[0], pair[1], line))
            continue
        tokens = seg.split(" ")
        if len(tokens) == 2 and _CJK_LABEL.match(tokens[0]) and len(tokens[1]) >= 2:
            facts.append(_fact(tokens[0], tokens[1], line))
    return facts


def _enum_option_fact(line: str) -> CandidateFact | None:
    """序号选项组(1.甲√ 2.乙 …,含勾选痕):整组枚举原文作值,不丢未选项。"""
    if "|" in line:
        return None
    match = _ENUM_LINE.match(line)
    if match is None:
        return None
    label, options = match.group(1), match.group(2)
    if not _ENUM_SECOND.search(options):
        return None  # 只有一个序号,不是选项组
    if not any(ch in _CHECKBOX_CHARS for ch in options):
        return None  # 无勾选痕的枚举(目录/条款)不是已填表单项
    return _fact(label, options, line)


def _multiline_option_facts(lines: list[str]) -> list[CandidateFact]:
    """短标签行 + 紧随的 ≥2 行带勾选框的序号/字母选项行 → 整组枚举作值。

    每个选项行都必须含勾选框符号(区分于目录/条款列表);evidence 取
    标签行到最后一个选项行的原文连续切片(可逐字定位)。
    """
    facts: list[CandidateFact] = []
    for i, raw in enumerate(lines):
        label = raw.strip()
        if not _OPTION_LABEL.match(label):
            continue
        j = i + 1
        options: list[str] = []
        while j < len(lines):
            option = lines[j].strip()
            if not (_OPTION_LINE.match(option)
                    and any(ch in _CHECKBOX_CHARS for ch in option)):
                break
            options.append(option)
            j += 1
        if len(options) < _MULTILINE_OPTION_MIN:
            continue
        facts.append(_fact(label, " ".join(options), "\n".join(lines[i:j])))
    return facts


def parse_structure_facts(full_text: str) -> list[CandidateFact]:
    """从底稿抽取版面结构事实;无结构不产出。精确规则在前,行打包在后。"""
    lines = full_text.splitlines()
    facts: list[CandidateFact] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        facts.extend(_wide_space_facts(line))
        enum_fact = _enum_option_fact(line)
        if enum_fact is not None:
            facts.append(enum_fact)
    facts.extend(_question_answer_facts(lines))
    facts.extend(_multiline_option_facts(lines))
    for raw in lines:
        line = raw.strip()
        if line:
            row_fact = _table_row_fact(line)
            if row_fact is not None:
                facts.append(row_fact)
    seen: set[tuple[str, str]] = set()
    deduped: list[CandidateFact] = []
    for fact in facts:
        dedup = (fact.key, fact.value)
        if dedup in seen:
            continue
        seen.add(dedup)
        deduped.append(fact)
    return deduped


def _norm_value(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch not in _STRIP_FOR_DEDUP)


def union_superset_facts(
    existing: list[CandidateFact], candidates: list[CandidateFact]
) -> list[CandidateFact]:
    """单向并集:候选值已被某现有值覆盖(归一化子串)才丢弃;超集保留。

    与 union_kv_facts 的双向去重不同:表格行打包值往往是某个现有值的
    超集且携带新信息(同行其余格),因"包含旧值"而丢弃会损失事实。
    """
    merged = list(existing)
    norms = [_norm_value(f.value) for f in existing if f.value.strip()]
    for cand in candidates:
        nv = _norm_value(cand.value)
        if not nv:
            continue
        if any(nv in ex for ex in norms):
            continue
        merged.append(cand)
        norms.append(nv)
    return merged
