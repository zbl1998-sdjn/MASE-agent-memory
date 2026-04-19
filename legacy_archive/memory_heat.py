from __future__ import annotations

from datetime import datetime
from typing import Any

HOT_QUERY_MARKERS = (
    "刚才",
    "刚刚",
    "刚说",
    "今天",
    "最近",
    "最新",
    "现在",
    "当前",
    "recent",
    "latest",
    "just",
    "today",
    "current",
)

COLD_QUERY_MARKERS = (
    "之前",
    "上次",
    "前面",
    "最开始",
    "最早",
    "以前",
    "历史",
    "当时",
    "去年",
    "上个月",
    "earlier",
    "previous",
    "before",
    "history",
    "last week",
    "last month",
)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def infer_query_heat(user_question: str) -> str:
    question = user_question.strip()
    if not question:
        return "neutral"
    if _contains_any(question, HOT_QUERY_MARKERS):
        return "hot"
    if _contains_any(question, COLD_QUERY_MARKERS):
        return "cold"
    return "neutral"


def _parse_result_datetime(item: dict[str, Any]) -> datetime | None:
    timestamp = str(item.get("timestamp") or "").strip()
    if timestamp:
        try:
            return datetime.fromisoformat(timestamp)
        except ValueError:
            pass

    date_value = str(item.get("date") or "").strip()
    time_value = str(item.get("time") or "").strip()
    if not date_value:
        return None

    for pattern in ("%Y-%m-%d %H-%M-%S-%f", "%Y-%m-%d %H-%M-%S", "%Y-%m-%d %H:%M:%S"):
        candidate = f"{date_value} {time_value or '00-00-00'}".strip()
        try:
            return datetime.strptime(candidate, pattern)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(date_value)
    except ValueError:
        return None


def infer_results_heat(search_results: list[dict[str, Any]]) -> str:
    parsed = [_parse_result_datetime(item) for item in search_results[:3]]
    datetimes = [item for item in parsed if item is not None]
    if not datetimes:
        return "neutral"

    now = datetime.now()
    ages_in_hours = [(now - item).total_seconds() / 3600 for item in datetimes]
    youngest = min(ages_in_hours)
    average = sum(ages_in_hours) / len(ages_in_hours)

    if youngest <= 24 or average <= 36:
        return "hot"
    if average >= 168:
        return "cold"
    return "neutral"


def resolve_memory_heat(user_question: str, search_results: list[dict[str, Any]] | None = None) -> str:
    query_heat = infer_query_heat(user_question)
    if query_heat != "neutral":
        return query_heat
    if search_results:
        return infer_results_heat(search_results)
    return "neutral"
