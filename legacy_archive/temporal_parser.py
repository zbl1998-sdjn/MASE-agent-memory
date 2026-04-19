from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

TemporalGranularity = Literal["minute", "day", "week", "unknown"]
TemporalRelation = Literal["point", "bounded", "before", "after"]

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_NUMBER_WORDS = {
    "a": 1,
    "an": 1,
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
_LONGMEMEVAL_PATTERNS = (
    "%Y/%m/%d (%a) %H:%M",
    "%Y/%m/%d (%A) %H:%M",
    "%Y/%m/%d %H:%M",
)


@dataclass(frozen=True)
class TemporalRange:
    start: datetime | None
    end: datetime | None
    granularity: TemporalGranularity = "unknown"
    relation: TemporalRelation = "bounded"
    confidence: float = 1.0
    source_text: str = ""
    start_inclusive: bool = True
    end_inclusive: bool = True

    def contains(self, value: datetime) -> bool:
        if self.start is not None:
            if self.start_inclusive and value < self.start:
                return False
            if not self.start_inclusive and value <= self.start:
                return False
        if self.end is not None:
            if self.end_inclusive and value > self.end:
                return False
            if not self.end_inclusive and value >= self.end:
                return False
        return True

    def is_bounded(self) -> bool:
        return self.start is not None or self.end is not None


def parse_reference_datetime(reference: str | datetime | None) -> datetime | None:
    if reference is None:
        return None
    if isinstance(reference, datetime):
        return reference
    return parse_temporal_datetime(reference)


def parse_temporal_datetime(text: str, reference: str | datetime | None = None) -> datetime | None:
    source = str(text or "").strip()
    if not source:
        return None

    parsed = _parse_iso_datetime(source)
    if parsed is not None:
        return parsed

    parsed = _parse_longmemeval_datetime(source)
    if parsed is not None:
        return parsed

    parsed = _parse_relative_weekday_datetime(source, reference=reference)
    if parsed is not None:
        return parsed

    parsed = _parse_month_day_datetime(source, reference=reference)
    if parsed is not None:
        return parsed
    return None


def parse_temporal_range(text: str, reference: str | datetime | None = None) -> TemporalRange | None:
    source = str(text or "").strip()
    if not source:
        return None

    reference_dt = parse_reference_datetime(reference)
    lowered = source.lower().strip()

    day_shift_match = re.match(r"^\s*(?:the\s+)?day\s+(before|after)\s+(.+?)\s*$", source, flags=re.IGNORECASE)
    if day_shift_match:
        relation = day_shift_match.group(1).lower()
        anchor_text = day_shift_match.group(2).strip()
        anchor_range = parse_temporal_range(anchor_text, reference=reference_dt)
        if anchor_range is None:
            anchor_dt = parse_temporal_datetime(anchor_text, reference=reference_dt)
            if anchor_dt is None:
                return None
            anchor_range = TemporalRange(
                start=anchor_dt,
                end=anchor_dt,
                granularity="minute",
                relation="point",
                confidence=0.9,
                source_text=anchor_text,
            )
        anchor_dt = anchor_range.start or anchor_range.end
        if anchor_dt is None:
            return None
        target_date = anchor_dt.date() - timedelta(days=1 if relation == "before" else -1)
        return _day_range(target_date, source_text=source, confidence=max(0.88, anchor_range.confidence - 0.02))

    relation_match = re.match(r"^\s*(before|after)\s+(.+?)\s*$", lowered, flags=re.IGNORECASE)
    if relation_match:
        relation = relation_match.group(1).lower()
        anchor_text = source[relation_match.start(2) : relation_match.end(2)]
        anchor_range = parse_temporal_range(anchor_text, reference=reference_dt)
        if anchor_range is None:
            anchor_dt = parse_temporal_datetime(anchor_text, reference=reference_dt)
            if anchor_dt is None:
                return None
            anchor_range = TemporalRange(
                start=anchor_dt,
                end=anchor_dt,
                granularity="minute",
                relation="point",
                confidence=0.92,
                source_text=anchor_text,
            )
        if relation == "before":
            anchor_end = anchor_range.start if anchor_range.start is not None else anchor_range.end
            return TemporalRange(
                start=None,
                end=anchor_end,
                granularity=anchor_range.granularity,
                relation="before",
                confidence=max(0.85, anchor_range.confidence - 0.03),
                source_text=source,
                end_inclusive=False,
            )
        anchor_start = anchor_range.end if anchor_range.end is not None else anchor_range.start
        return TemporalRange(
            start=anchor_start,
            end=None,
            granularity=anchor_range.granularity,
            relation="after",
            confidence=max(0.85, anchor_range.confidence - 0.03),
            source_text=source,
            start_inclusive=False,
        )

    if "last week" in lowered:
        if reference_dt is None:
            return None
        start, end = _last_week_range(reference_dt)
        return TemporalRange(
            start=start,
            end=end,
            granularity="week",
            relation="bounded",
            confidence=0.96,
            source_text=source,
        )

    rolling_window_match = re.search(
        r"\b(?:past|last)\s+(?:(?P<count>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+)?"
        r"(?P<unit>days?|weeks?|months?)\b",
        lowered,
        flags=re.IGNORECASE,
    )
    if rolling_window_match:
        if reference_dt is None:
            return None
        count = _parse_number_token(rolling_window_match.group("count") or "one")
        if count is None:
            return None
        unit = rolling_window_match.group("unit").lower()
        if unit.startswith("day"):
            start_dt = datetime.combine(reference_dt.date() - timedelta(days=count), time.min)
            granularity: TemporalGranularity = "day"
        elif unit.startswith("week"):
            start_dt = datetime.combine(reference_dt.date() - timedelta(weeks=count), time.min)
            granularity = "week"
        else:
            start_dt = datetime.combine(_shift_months(reference_dt.date(), -count), time.min)
            granularity = "day"
        return TemporalRange(
            start=start_dt,
            end=datetime.combine(reference_dt.date(), time.max),
            granularity=granularity,
            relation="bounded",
            confidence=0.93,
            source_text=source,
        )

    weeks_ago_match = re.search(
        r"\b(?P<count>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+weeks?\s+ago\b",
        lowered,
        flags=re.IGNORECASE,
    )
    if weeks_ago_match:
        if reference_dt is None:
            return None
        count = _parse_number_token(weeks_ago_match.group("count"))
        if count is None:
            return None
        target = reference_dt - timedelta(weeks=count)
        return _day_range(target.date(), source_text=source, confidence=0.94)

    relative_days_months_match = re.search(
        r"\b(?P<count>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(?P<unit>days?|months?)\s+ago\b",
        lowered,
        flags=re.IGNORECASE,
    )
    if relative_days_months_match:
        if reference_dt is None:
            return None
        count = _parse_number_token(relative_days_months_match.group("count"))
        if count is None:
            return None
        unit = relative_days_months_match.group("unit").lower()
        if unit.startswith("day"):
            target_date = reference_dt.date() - timedelta(days=count)
        else:
            target_date = _shift_months(reference_dt.date(), -count)
        return _day_range(target_date, source_text=source, confidence=0.94)

    explicit_point = _parse_iso_datetime(source) or _parse_longmemeval_datetime(source)
    if explicit_point is not None:
        return TemporalRange(
            start=explicit_point,
            end=explicit_point,
            granularity="minute",
            relation="point",
            confidence=0.99,
            source_text=source,
        )

    month_day_range = _parse_month_day_range(source, reference=reference_dt)
    if month_day_range is not None:
        start_date, end_date = month_day_range
        return TemporalRange(
            start=datetime.combine(start_date, time.min),
            end=datetime.combine(end_date, time.max),
            granularity="day",
            relation="bounded",
            confidence=0.95 if start_date != end_date else 0.97,
            source_text=source,
        )

    parsed = parse_temporal_datetime(source, reference=reference_dt)
    if parsed is not None:
        return TemporalRange(
            start=parsed,
            end=parsed,
            granularity="minute",
            relation="point",
            confidence=0.99,
            source_text=source,
        )
    return None


def _parse_iso_datetime(text: str) -> datetime | None:
    candidate = text.strip()
    if not candidate:
        return None
    normalized = candidate.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_longmemeval_datetime(text: str) -> datetime | None:
    candidate = text.strip()
    for pattern in _LONGMEMEVAL_PATTERNS:
        try:
            return datetime.strptime(candidate, pattern)
        except ValueError:
            continue
    simplified = re.sub(r"\s+\([A-Za-z]{3,9}\)\s+", " ", candidate)
    for pattern in ("%Y/%m/%d %H:%M",):
        try:
            return datetime.strptime(simplified, pattern)
        except ValueError:
            continue
    return None


def _parse_relative_weekday_datetime(text: str, reference: str | datetime | None = None) -> datetime | None:
    reference_dt = parse_reference_datetime(reference)
    if reference_dt is None:
        return None
    match = re.match(
        r"^\s*(?:(?P<modifier>last|this)\s+)?(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"(?:\s+(?:at\s+)?(?P<clock>\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2}))?\s*$",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    modifier = str(match.group("modifier") or "").lower()
    weekday_name = match.group("weekday").lower()
    weekday_index = _WEEKDAYS[weekday_name]
    if modifier == "this":
        week_start = reference_dt.date() - timedelta(days=reference_dt.weekday())
        target_date = week_start + timedelta(days=weekday_index)
        if target_date > reference_dt.date():
            target_date -= timedelta(days=7)
    else:
        days_back = (reference_dt.weekday() - weekday_index) % 7
        if modifier == "last" and days_back == 0:
            days_back = 7
        target_date = reference_dt.date() - timedelta(days=days_back)
    return datetime.combine(target_date, _parse_clock_time(match.group("clock")))


def _parse_month_day_datetime(text: str, reference: str | datetime | None = None) -> datetime | None:
    month_day_range = _parse_month_day_range(text, reference=parse_reference_datetime(reference))
    if month_day_range is None:
        return None
    return datetime.combine(month_day_range[0], time.min)


def _parse_month_day_range(text: str, reference: datetime | None = None) -> tuple[date, date] | None:
    source = str(text or "").strip()
    if not source:
        return None
    year = reference.year if reference is not None else datetime.now().year

    named_match = re.search(
        r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|november|december)\s+"
        r"(?P<day1>\d{1,2})(?:st|nd|rd|th)?"
        r"(?:\s*(?:-|to|through|until)\s*(?P<day2>\d{1,2})(?:st|nd|rd|th)?)?"
        r"(?:,\s*(?P<year>\d{4}))?\b",
        source,
        flags=re.IGNORECASE,
    )
    if named_match:
        matched_year = int(named_match.group("year")) if named_match.group("year") else year
        month = _MONTHS[named_match.group("month").lower()]
        day1 = int(named_match.group("day1"))
        day2 = int(named_match.group("day2")) if named_match.group("day2") else day1
        return _safe_date_range(matched_year, month, day1, day2)

    numeric_match = re.search(
        r"\b(?P<month>\d{1,2})/(?P<day1>\d{1,2})(?:/(?P<year>\d{2,4}))?"
        r"(?:\s*(?:-|to|through|until)\s*(?P<day2>\d{1,2}))?\b",
        source,
        flags=re.IGNORECASE,
    )
    if numeric_match:
        matched_year = _normalize_year_token(numeric_match.group("year"), fallback_year=year)
        month = int(numeric_match.group("month"))
        day1 = int(numeric_match.group("day1"))
        day2 = int(numeric_match.group("day2")) if numeric_match.group("day2") else day1
        return _safe_date_range(matched_year, month, day1, day2)
    return None


def _normalize_year_token(raw_year: str | None, fallback_year: int) -> int:
    if not raw_year:
        return fallback_year
    value = int(raw_year)
    if value < 100:
        return 2000 + value
    return value


def _safe_date_range(year: int, month: int, day1: int, day2: int) -> tuple[date, date] | None:
    if day2 < day1:
        return None
    try:
        start = date(year, month, day1)
        end = date(year, month, day2)
    except ValueError:
        return None
    return start, end


def _parse_clock_time(raw_value: str | None) -> time:
    candidate = str(raw_value or "").strip().lower()
    if not candidate:
        return time.min
    meridiem_match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", candidate, flags=re.IGNORECASE)
    if meridiem_match:
        hour = int(meridiem_match.group(1)) % 12
        minute = int(meridiem_match.group(2) or 0)
        if meridiem_match.group(3).lower() == "pm":
            hour += 12
        return time(hour=hour, minute=minute)
    military_match = re.fullmatch(r"(\d{1,2}):(\d{2})", candidate)
    if military_match:
        hour = int(military_match.group(1))
        minute = int(military_match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour=hour, minute=minute)
    return time.min


def _parse_number_token(token: str) -> int | None:
    normalized = str(token or "").strip().lower()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)
    return _NUMBER_WORDS.get(normalized)


def _shift_months(target_date: date, delta_months: int) -> date:
    month_index = target_date.month - 1 + delta_months
    year = target_date.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(target_date.day, last_day))


def _last_week_range(reference_dt: datetime) -> tuple[datetime, datetime]:
    current_week_start = datetime.combine(reference_dt.date(), time.min) - timedelta(days=reference_dt.weekday())
    last_week_start = current_week_start - timedelta(days=7)
    last_week_end = current_week_start - timedelta(microseconds=1)
    return last_week_start, last_week_end


def _day_range(target_date: date, source_text: str, confidence: float) -> TemporalRange:
    return TemporalRange(
        start=datetime.combine(target_date, time.min),
        end=datetime.combine(target_date, time.max),
        granularity="day",
        relation="bounded",
        confidence=confidence,
        source_text=source_text,
    )


__all__ = [
    "TemporalRange",
    "parse_reference_datetime",
    "parse_temporal_datetime",
    "parse_temporal_range",
]
