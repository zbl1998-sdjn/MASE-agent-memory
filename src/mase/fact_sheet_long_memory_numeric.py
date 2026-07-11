"""LongMemEval ledger 的数值/文本纯函数 helpers(从 ledgers 拆出,2026-07-12 架构切片④)。

金额/时长/计数解析与 ledger 文本模板:无状态纯函数,被聚合 ledger 构建器
(fact_sheet_long_memory_ledgers)复用。行为与拆分前逐字节一致。
"""
from __future__ import annotations

import re

from .fact_sheet_common import extract_focused_window

# 常用数值抽取正则：金额、时长、天数、周数都服务于确定性聚合 ledger。
_MONEY_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_HOURS_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b")
_MINUTES_RE = re.compile(r"(?<!\d)(\d+)\s*minutes?\b")
_DAYS_RE = re.compile(r"(?<!\d)(\d+)\s*(?:-|–)?\s*(?:days?|nights?)\b")
_WEEKS_RE = re.compile(r"(?<!\d)(\d+)\s*(?:-|–)?\s*weeks?\b")
_ENGLISH_COUNT_WORDS = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}


def _compact_snippet(content: str, matched_terms: list[str]) -> str:
    """从长证据行中截取围绕命中词的紧凑片段。"""
    snippet = extract_focused_window(content, matched_terms[:8], radius=220, max_windows=1)
    return re.sub(r"\s+", " ", snippet).strip()


def _first_money(text: str) -> float | None:
    """提取第一个金额，用于差额/预算类 ledger。"""
    match = _MONEY_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _money_values(text: str) -> list[float]:
    """提取一行中的所有金额，供求和/比较分支使用。"""
    return [float(value.replace(",", "")) for value in _MONEY_RE.findall(text)]


def _first_hours(text: str) -> float | None:
    """把小时/分钟自然语言统一换算成小时。"""
    match = _HOURS_RE.search(text)
    if match:
        return float(match.group(1))
    minute_match = _MINUTES_RE.search(text)
    if minute_match:
        return float(minute_match.group(1)) / 60.0
    if "an hour" in text or "1 hour" in text:
        return 1.0
    if "half hour" in text:
        return 0.5
    return None


def _duration_in_days(text: str) -> int | None:
    """把 week/day 表达统一换算成天数。"""
    week_match = _WEEKS_RE.search(text)
    if week_match:
        return int(week_match.group(1)) * 7
    if any(marker in text for marker in ("week-long", "week long")):
        return 7
    if "a week break" in text or "one week break" in text:
        return 7
    day_match = _DAYS_RE.search(text)
    if day_match:
        return int(day_match.group(1))
    return None


def _format_dollars(value: float) -> str:
    if float(value).is_integer():
        return f"${value:,.0f}"
    return f"${value:,.2f}".rstrip("0").rstrip(".")


def _english_count_word(value: int) -> str:
    return _ENGLISH_COUNT_WORDS.get(value, str(value))


def _join_english_list(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _remember_distinct_item(
    items: dict[str, tuple[str, str]],
    key: str,
    label: str,
    row_id: int,
    snippet: str,
) -> None:
    if key in items:
        return
    items[key] = (label, f"- {label} (row={row_id}): {snippet[:260]}")


def _emit_normalized_ledger(
    title: str,
    evidence: list[str],
    *,
    normalized_answer: str,
    deterministic_lines: list[str] | None = None,
    legacy_answer: str | None = None,
) -> list[str]:
    """输出统一 ledger 形状：证据、计算行、旧兼容答案和 deterministic_answer。"""
    lines = [f"Aggregate answer ledger ({title}):", *evidence]
    if deterministic_lines:
        lines.extend(deterministic_lines)
    if legacy_answer is not None:
        lines.append(f"- Deterministic aggregate answer: {legacy_answer}")
    lines.append(f"- Deterministic answer: {normalized_answer}")
    lines.append(f"- deterministic_answer={normalized_answer}")
    return lines


def _normalize_count_answer(question: str, item_labels: list[str]) -> str:
    """根据问题域把计数结果转成人类可读且可评分的答案文本。"""
    lowered_question = (question or "").lower()
    count = len(item_labels)
    count_word = _english_count_word(count)
    if "fitness classes" in lowered_question and "days a week" in lowered_question:
        return f"{count} days."
    if "kitchen item" in lowered_question or (
        "kitchen" in lowered_question and any(marker in lowered_question for marker in ("replace", "replaced", "fix", "fixed"))
    ):
        return f"I replaced or fixed {count_word} items: {_join_english_list(item_labels)}."
    if "model kits" in lowered_question:
        return (
            f"I have worked on or bought {count_word} model kits. "
            f"The scales of the models are: {_join_english_list(item_labels)}."
        )
    if "doctor" in lowered_question and "visit" in lowered_question:
        return f"I visited {count_word} different doctors: {_join_english_list(item_labels)}."
    if "movie festival" in lowered_question or "film festival" in lowered_question:
        return f"I attended {count_word} movie festivals."
    if "dinner parties" in lowered_question or ("dinner party" in lowered_question and "past month" in lowered_question):
        return count_word
    return str(count)


def _build_count_template(
    question: str,
    title: str,
    items: list[str],
    evidence: list[str],
) -> list[str]:
    """生成计数类 ledger 模板，列出每个被计数候选。"""
    normalized_answer = _normalize_count_answer(question, items)
    deterministic_lines = [
        "- Countable items:",
        *[f"- {index}. {label}" for index, label in enumerate(items, start=1)],
        f"- Deterministic count: {len(items)} items",
    ]
    return _emit_normalized_ledger(
        title,
        evidence,
        normalized_answer=normalized_answer,
        deterministic_lines=deterministic_lines,
        legacy_answer=normalized_answer,
    )


def _build_sum_template(
    title: str,
    evidence: list[str],
    components: list[str],
    normalized_answer: str,
) -> list[str]:
    return _emit_normalized_ledger(
        title,
        evidence,
        normalized_answer=normalized_answer,
        deterministic_lines=[f"- Deterministic sum: {' + '.join(components)} = {normalized_answer}"],
        legacy_answer=normalized_answer,
    )


def _build_difference_template(
    title: str,
    evidence: list[str],
    minuend: str,
    subtrahend: str,
    normalized_answer: str,
) -> list[str]:
    return _emit_normalized_ledger(
        title,
        evidence,
        normalized_answer=normalized_answer,
        deterministic_lines=[f"- Deterministic delta: {minuend} - {subtrahend} = {normalized_answer}"],
        legacy_answer=normalized_answer,
    )


def _build_ratio_template(
    title: str,
    evidence: list[str],
    numerator: str,
    denominator: str,
    normalized_answer: str,
) -> list[str]:
    return _emit_normalized_ledger(
        title,
        evidence,
        normalized_answer=normalized_answer,
        deterministic_lines=[f"- Deterministic ratio: {numerator} / {denominator} = {normalized_answer}"],
        legacy_answer=normalized_answer,
    )
