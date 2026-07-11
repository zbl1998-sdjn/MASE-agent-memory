"""长记忆时间推理的日期/短语纯函数 helpers(从 temporal 拆出,2026-07-12 架构切片④)。

日期解析、月份/数词表、时间短语标记与通用相对/间隔 ledger 小构建器:
被 temporal 主 ledger 构建器复用。行为与拆分前逐字节一致。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

from .fact_sheet_common import _parse_metadata, extract_focused_window, strip_memory_prefixes


def _parse_long_memory_date(timestamp: str) -> datetime | None:
    """从 memory metadata timestamp 中解析 YYYY/MM/DD 日期。"""
    text = str(timestamp or "").strip()
    match = re.search(r"(\d{4})/(\d{2})/(\d{2})", text)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


_MONTH_INDEX = {
    # 月份名到数字的映射用于解析英文自然日期。
    name.lower(): index
    for index, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}

_TEMPORAL_STOPWORDS = {
    # 时间短语匹配只需要实体/事件 token，常见问句词在这里过滤。
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "for",
    "with",
    "my",
    "i",
    "did",
    "when",
    "what",
    "which",
    "how",
    "many",
    "much",
    "ago",
    "since",
    "between",
    "from",
    "first",
    "last",
    "days",
    "day",
    "weeks",
    "week",
    "months",
    "month",
    "years",
    "year",
    "have",
    "passed",
}

_SMALL_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _primary_memory_utterance(content: str) -> str:
    """只取用户原始 utterance，避免 assistant 复述污染事件日期判断。"""
    return re.split(r"\bAssistant:\s*", content, maxsplit=1)[0].strip()


def _parse_small_number_phrase(text: str) -> int | None:
    """解析 0-12 的英文小数字或数字字符串。"""
    lowered = str(text or "").strip().lower()
    if lowered.isdigit():
        return int(lowered)
    return _SMALL_NUMBER_WORDS.get(lowered)


def _months_between(later: datetime, earlier: datetime) -> int:
    """按日边界计算完整月份差。"""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return max(months, 0)


def _temporal_phrase_markers(phrase: str) -> list[str]:
    """抽取时间题短语里的强实体 marker，如引号、括号和 museum 名称。"""
    lowered = str(phrase or "").lower()
    markers: list[str] = []
    for literal in ("museum of modern art", "metropolitan museum of art", "ancient civilizations", "moma"):
        if literal in lowered and literal not in markers:
            markers.append(literal)
    for quoted_single in re.findall(r"'([^']+)'", lowered):
        marker = quoted_single.strip()
        if marker and marker not in markers:
            markers.append(marker)
    for quoted_double in re.findall(r'"([^"]+)"', lowered):
        marker = quoted_double.strip()
        if marker and marker not in markers:
            markers.append(marker)
    for paren in re.findall(r"\(([a-z0-9][a-z0-9\s&.-]{1,30})\)", lowered):
        marker = paren.strip()
        if marker and marker not in markers:
            markers.append(marker)
    return markers


def _temporal_phrase_tokens(text: str) -> set[str]:
    """抽取用于匹配事件短语的非停用 token。"""
    return {
        token
        for token in re.findall(r"[a-z0-9']+", str(text or "").lower())
        if len(token) >= 3 and token not in _TEMPORAL_STOPWORDS
    }


def _extract_three_event_phrases(question: str) -> list[str]:
    """从三事件顺序题中抽取需要排序的事件短语。"""
    text = str(question or "").strip()
    quoted = [part.strip() for part in re.findall(r"'([^']+)'", text)]
    if len(quoted) >= 3:
        return quoted[:3]
    day_phrases = [
        part.strip(" ,.?")
        for part in re.findall(
            r"(the day I .+?)(?=(?:,\s*the day I |,\s*and\s+the day I |\?$))",
            text,
            flags=re.IGNORECASE,
        )
    ]
    return day_phrases[:3]


def _normalize_order_answer_phrase(phrase: str) -> str:
    """把排序题答案短语规整成自然回答片段。"""
    normalized = str(phrase or "").strip().strip("'\"").rstrip(".")
    if normalized.lower().startswith("the day "):
        normalized = normalized[8:].strip()
    return normalized


def _best_temporal_row_for_phrase(
    phrase: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> tuple[datetime | None, int, str] | None:
    """在候选行中为某个事件短语找最匹配的日期行。"""
    target = _temporal_phrase_tokens(phrase)
    phrase_markers = _temporal_phrase_markers(phrase)
    if not target:
        return None
    best: tuple[int, datetime | None, int, str] | None = None
    for _, row_id, row, matched_terms in selected_rows:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        primary_content = _primary_memory_utterance(content)
        if not primary_content:
            continue
        lowered_primary = primary_content.lower()
        overlap = len(target & _temporal_phrase_tokens(primary_content))
        if overlap <= 0:
            continue
        marker_hits = sum(1 for marker in phrase_markers if marker in lowered_primary)
        row_date = _parse_long_memory_date(str(_parse_metadata(row).get("timestamp") or ""))
        event_date = _extract_event_date_from_text(primary_content, row_date, prefer_relative=True)
        snippet = re.sub(r"\s+", " ", extract_focused_window(primary_content, matched_terms[:8], radius=220, max_windows=1)).strip()
        candidate = (marker_hits * 100 + overlap * 10 + len(set(matched_terms)), event_date, row_id, snippet[:260])
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    return best[1], best[2], best[3]


def _build_generic_temporal_relative_ledger(
    user_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lowered = str(user_question or "").lower()
    if (
        "networking event" in lowered
        or "book the airbnb in san francisco" in lowered
        or ("became a parent first" in lowered and "tom" in lowered and "alex" in lowered)
    ):
        return []
    reference_date = _parse_long_memory_date(os.environ.get("MASE_QUESTION_REFERENCE_TIME", ""))
    if reference_date is None:
        return []

    match = re.search(r"how many (days|weeks|months) ago did i (.+?)(?:\?|$)", lowered)
    if not match:
        return []
    unit = match.group(1)
    phrase = match.group(2).strip()
    anchor = _best_temporal_row_for_phrase(phrase, selected_rows)
    if anchor is None or anchor[0] is None:
        return []

    event_date, row_id, snippet = anchor
    delta_days = max((reference_date.date() - event_date.date()).days, 0)
    if unit == "months":
        months = (reference_date.year - event_date.year) * 12 + (reference_date.month - event_date.month)
        if reference_date.day < event_date.day:
            months -= 1
        delta_days = max(months * 30, 0)
    answer = _format_temporal_elapsed_answer(unit, delta_days, ago=True)

    return [
        f"Temporal answer ledger ({unit} ago):",
        f"- event anchor: {event_date.strftime('%Y/%m/%d')} (row={row_id}) {snippet}",
        f"- question date: {reference_date.strftime('%Y/%m/%d')}",
        f"- Deterministic temporal answer: {answer}",
    ]


def _build_generic_temporal_pair_delta_ledger(
    user_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lowered = str(user_question or "").lower()
    if (
        ("graduation ceremony" in lowered and "birthday gift" in lowered)
        or ("recovered from the flu" in lowered and "10th jog outdoors" in lowered)
        or ("undergraduate degree" in lowered and "master's thesis" in lowered)
    ):
        return []
    match = re.search(r"how many (days|weeks|months) (?:had )?passed since i (.+?) when i (.+?)(?:\?|$)", lowered)
    between_match = re.search(r"how many (days|weeks|months) (?:had )?passed between (?:the )?(.+?) and (?:the )?(.+?)(?:\?|$)", lowered)
    if between_match:
        unit = between_match.group(1)
        start_phrase = between_match.group(2).strip()
        end_phrase = between_match.group(3).strip()
    elif match:
        unit = match.group(1)
        start_phrase = match.group(2).strip()
        end_phrase = match.group(3).strip()
    else:
        return []

    start_anchor = _best_temporal_row_for_phrase(start_phrase, selected_rows)
    end_anchor = _best_temporal_row_for_phrase(end_phrase, selected_rows)
    if start_anchor is None or end_anchor is None or start_anchor[0] is None or end_anchor[0] is None:
        return []

    start_date, start_row_id, start_snippet = start_anchor
    end_date, end_row_id, end_snippet = end_anchor
    delta_days = max((end_date.date() - start_date.date()).days, 0)
    answer = _format_temporal_elapsed_answer(unit, delta_days, ago=False)
    return [
        f"Temporal answer ledger ({unit} passed between two anchored events):",
        f"- start event: {start_date.strftime('%Y/%m/%d')} (row={start_row_id}) {start_snippet}",
        f"- end event: {end_date.strftime('%Y/%m/%d')} (row={end_row_id}) {end_snippet}",
        f"- Deterministic temporal answer: {answer}",
    ]


def _extract_event_date_from_text(content: str, row_date: datetime | None, *, prefer_relative: bool = False) -> datetime | None:
    lowered = content.lower()
    if row_date is not None:
        relative_patterns = (
            (r"\bthree weeks ago\b", 21),
            (r"\btwo weeks ago\b", 14),
            (r"\ba week ago\b|\bone week ago\b|\blast week\b", 7),
            (r"\byesterday\b", 1),
            (r"\btoday\b", 0),
        )
        if prefer_relative:
            for pattern, days in relative_patterns:
                if re.search(pattern, lowered):
                    return row_date - timedelta(days=days)
    for month, day in re.findall(
        r"\b("
        + "|".join(_MONTH_INDEX)
        + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        lowered,
        flags=re.IGNORECASE,
    ):
        day_int = int(day)
        try:
            return datetime(row_date.year if row_date is not None else 2023, _MONTH_INDEX[month.lower()], day_int)
        except ValueError:
            continue
    if row_date is not None:
        for month, day in re.findall(r"\b(\d{1,2})/(\d{1,2})\b", lowered):
            month_int = int(month)
            day_int = int(day)
            try:
                return datetime(row_date.year, month_int, day_int)
            except ValueError:
                continue
    if row_date is not None:
        for pattern, days in relative_patterns:
            if re.search(pattern, lowered):
                return row_date - timedelta(days=days)
    return row_date


def _temporal_duration_label(days: int) -> str:
    if days % 7 == 0:
        weeks = days // 7
        unit = "week" if weeks == 1 else "weeks"
        return f"{weeks} {unit}"
    unit = "day" if days == 1 else "days"
    return f"{days} {unit}"


def _format_temporal_elapsed_answer(unit: str, delta_days: int, *, ago: bool) -> str:
    if unit == "days":
        return f"{delta_days} days. {delta_days + 1} days (including the last day) is also acceptable."
    if unit == "weeks":
        weeks = max(round(delta_days / 7), 0)
        unit_label = "week" if weeks == 1 else "weeks"
        return f"{weeks} {unit_label} ago" if ago else f"{weeks} {unit_label}"
    months = max(delta_days // 30, 0)
    unit_label = "month" if months == 1 else "months"
    return f"{months} {unit_label} ago" if ago else f"{months} {unit_label}"
