from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from temporal_parser import TemporalRange, parse_temporal_datetime, parse_temporal_range


def _assert_datetime(value: datetime | None, expected: datetime) -> None:
    assert value is not None, f"expected {expected!r}, got None"
    assert value == expected, f"expected {expected!r}, got {value!r}"


def test_parse_iso_datetime() -> None:
    parsed = parse_temporal_datetime("2023-05-30T23:40:00")
    _assert_datetime(parsed, datetime(2023, 5, 30, 23, 40, 0))


def test_parse_longmemeval_datetime() -> None:
    parsed = parse_temporal_datetime("2023/05/30 (Tue) 23:40")
    _assert_datetime(parsed, datetime(2023, 5, 30, 23, 40, 0))


def test_parse_official_question_date_sample() -> None:
    data_path = Path(__file__).resolve().parent / "data" / "longmemeval-official" / "longmemeval_oracle.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    first_temporal = next(item for item in data if item.get("question_type") == "temporal-reasoning")
    parsed = parse_temporal_datetime(str(first_temporal.get("question_date") or ""))
    _assert_datetime(parsed, datetime(2023, 4, 10, 23, 7, 0))


def test_parse_month_day_range() -> None:
    temporal_range = parse_temporal_range("March 15-16", reference=datetime(2023, 4, 10, 23, 7))
    assert temporal_range is not None
    _assert_datetime(temporal_range.start, datetime(2023, 3, 15, 0, 0, 0))
    _assert_datetime(temporal_range.end, datetime(2023, 3, 16, 23, 59, 59, 999999))
    assert temporal_range.granularity == "day"


def test_parse_last_week() -> None:
    temporal_range = parse_temporal_range("last week", reference=datetime(2023, 5, 30, 23, 40))
    assert temporal_range is not None
    _assert_datetime(temporal_range.start, datetime(2023, 5, 22, 0, 0, 0))
    _assert_datetime(temporal_range.end, datetime(2023, 5, 28, 23, 59, 59, 999999))
    assert temporal_range.granularity == "week"


def test_parse_two_weeks_ago() -> None:
    temporal_range = parse_temporal_range("two weeks ago", reference=datetime(2023, 5, 30, 23, 40))
    assert temporal_range is not None
    _assert_datetime(temporal_range.start, datetime(2023, 5, 16, 0, 0, 0))
    _assert_datetime(temporal_range.end, datetime(2023, 5, 16, 23, 59, 59, 999999))
    assert temporal_range.granularity == "day"


def test_parse_before_after() -> None:
    before_range = parse_temporal_range("before 2023/05/30 (Tue) 23:40")
    assert before_range is not None
    assert before_range.relation == "before"
    assert before_range.start is None
    _assert_datetime(before_range.end, datetime(2023, 5, 30, 23, 40, 0))
    assert before_range.end_inclusive is False

    after_range = parse_temporal_range("after March 15", reference=datetime(2023, 4, 10, 23, 7))
    assert after_range is not None
    assert after_range.relation == "after"
    _assert_datetime(after_range.start, datetime(2023, 3, 15, 23, 59, 59, 999999))
    assert after_range.end is None
    assert after_range.start_inclusive is False


def test_parse_relative_weekday_and_day_before_anchor() -> None:
    parsed = parse_temporal_datetime("last Wednesday", reference=datetime(2023, 5, 29, 15, 16))
    _assert_datetime(parsed, datetime(2023, 5, 24, 0, 0, 0))

    temporal_range = parse_temporal_range("day before last Thursday at 10 AM", reference=datetime(2023, 5, 30, 23, 40))
    assert temporal_range is not None
    _assert_datetime(temporal_range.start, datetime(2023, 5, 24, 0, 0, 0))
    _assert_datetime(temporal_range.end, datetime(2023, 5, 24, 23, 59, 59, 999999))


def test_parse_past_two_months() -> None:
    temporal_range = parse_temporal_range("past two months", reference=datetime(2023, 5, 30, 23, 40))
    assert temporal_range is not None
    _assert_datetime(temporal_range.start, datetime(2023, 3, 30, 0, 0, 0))
    _assert_datetime(temporal_range.end, datetime(2023, 5, 30, 23, 59, 59, 999999))


def test_contains_open_range() -> None:
    temporal_range = TemporalRange(
        start=datetime(2023, 5, 30, 23, 40, 0),
        end=None,
        granularity="minute",
        relation="after",
        start_inclusive=False,
        source_text="after 2023-05-30T23:40:00",
    )
    assert temporal_range.contains(datetime(2023, 5, 30, 23, 41, 0)) is True
    assert temporal_range.contains(datetime(2023, 5, 30, 23, 40, 0)) is False


def main() -> None:
    test_parse_iso_datetime()
    test_parse_longmemeval_datetime()
    test_parse_official_question_date_sample()
    test_parse_month_day_range()
    test_parse_last_week()
    test_parse_two_weeks_ago()
    test_parse_before_after()
    test_parse_relative_weekday_and_day_before_anchor()
    test_parse_past_two_months()
    test_contains_open_range()
    print("temporal parser tests passed")


if __name__ == "__main__":
    main()
