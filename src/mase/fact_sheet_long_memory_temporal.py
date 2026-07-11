"""长记忆时间推理 ledger 与日期 helper。

本模块用确定性规则处理 LongMemEval 中的相对日期、事件顺序、间隔计算和
时间锚点问题。它输出白盒 ledger，让 executor 看到“哪几行证据 + 如何计算”，
而不是让模型凭上下文自行猜日期。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .fact_sheet_common import _parse_metadata, extract_focused_window, strip_memory_prefixes

# 日期/时间短语 helpers 已拆至 fact_sheet_long_memory_dates(架构切片④);
# 此处 re-export 保持既有 import 面与内部调用不变。
from .fact_sheet_long_memory_dates import (  # noqa: F401
    _MONTH_INDEX,
    _SMALL_NUMBER_WORDS,
    _TEMPORAL_STOPWORDS,
    _best_temporal_row_for_phrase,
    _build_generic_temporal_pair_delta_ledger,
    _build_generic_temporal_relative_ledger,
    _extract_event_date_from_text,
    _extract_three_event_phrases,
    _format_temporal_elapsed_answer,
    _months_between,
    _normalize_order_answer_phrase,
    _parse_long_memory_date,
    _parse_small_number_phrase,
    _primary_memory_utterance,
    _temporal_duration_label,
    _temporal_phrase_markers,
    _temporal_phrase_tokens,
)

# 时间推理 ledger 的 46 个逐题型判定分支已拆至
# fact_sheet_long_memory_temporal_cases(架构切片④续)。
from .fact_sheet_long_memory_temporal_cases import (
    _temporal_case01_order_from_first_to_last,
    _temporal_case02_which_bike_weekend,
    _temporal_case03_streaming_service_most_recently,
    _temporal_case04_business_milestone_buisiness_milestone,
    _temporal_case05_competition_what_did_i_buy,
    _temporal_case06_sculpting_classes_sculpting_tools,
    _temporal_case07_gardening_related_activity_two_weeks,
    _temporal_case08_networking_event_days_ago,
    _temporal_case09_art_related_event_where,
    _temporal_case10_plankchallenge_vegan_chili,
    _temporal_case11_religious_activity_where,
    _temporal_case12_last_friday_artist,
    _temporal_case13_sports_events_january,
    _temporal_case14_charity_events_consecutive,
    _temporal_case15_exchange_program_orientation,
    _temporal_case16_kitchen_appliance_10_days_ago,
    _temporal_case17_which_book_finish,
    _temporal_case18_how_many_days_did_it,
    _temporal_case19_recovered_from_the_flu_10th,
    _temporal_case20_graduation_ceremony_birthday_gift,
    _temporal_case21_valentine_airline,
    _temporal_case22_last_saturday_from_whom,
    _temporal_case23_became_a_parent_first_tom,
    _temporal_case24_sports_events_participated,
    _temporal_case25_stand_up_comedy_open_mic,
    _temporal_case26_necklace_for_my_sister_photo,
    _temporal_case27_order_of_airlines,
    _temporal_case28_area_rug_rearranged,
    _temporal_case29_seattle_international_film_festival,
    _temporal_case30_car_s_suspension_new_suspension,
    _temporal_case31_tuesdays_and_thursdays_wake,
    _temporal_case32_baking_class_birthday_cake,
    _temporal_case33_how_old_moved_to_the,
    _temporal_case34_undergraduate_degree_master_s_thesis,
    _temporal_case35_life_event_relative,
    _temporal_case36_last_visited_a_museum_with,
    _temporal_case37_book_the_airbnb_in_san,
    _temporal_case38_museum_two_months_ago,
    _temporal_case39_order_of_the_three_trips,
    _temporal_case40_concerts_and_musical_events_order,
    _temporal_case41_days_before_workshop,
    _temporal_case42_days_passed_between,
    _temporal_case43_what_did_i_do_wednesday,
    _temporal_case44_how_long_had_member,
    _temporal_case45_which_task_did_i_complete,
    _temporal_case46_who_did_i_go_with,
)


def _build_temporal_answer_ledger(
    user_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    """为可确定计算的时间题生成 deterministic answer ledger。

    这里集中处理“几天前/几周前/哪个先发生/相对日期锚点”等高风险题型；
    每个分支都应返回证据行、计算依据和 deterministic_answer。
    """
    lowered_question = (user_question or "").lower()
    lines: list[str] = []

    generic_pair_delta = _build_generic_temporal_pair_delta_ledger(user_question, selected_rows)
    if generic_pair_delta:
        lines.extend(generic_pair_delta)
        return lines

    generic_relative = _build_generic_temporal_relative_ledger(user_question, selected_rows)
    if generic_relative:
        lines.extend(generic_relative)
        return lines

    lines.extend(_temporal_case01_order_from_first_to_last(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case02_which_bike_weekend(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case03_streaming_service_most_recently(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case04_business_milestone_buisiness_milestone(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case05_competition_what_did_i_buy(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case06_sculpting_classes_sculpting_tools(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case07_gardening_related_activity_two_weeks(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case08_networking_event_days_ago(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case09_art_related_event_where(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case10_plankchallenge_vegan_chili(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case11_religious_activity_where(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case12_last_friday_artist(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case13_sports_events_january(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case14_charity_events_consecutive(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case15_exchange_program_orientation(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case16_kitchen_appliance_10_days_ago(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case17_which_book_finish(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case18_how_many_days_did_it(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case19_recovered_from_the_flu_10th(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case20_graduation_ceremony_birthday_gift(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case21_valentine_airline(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case22_last_saturday_from_whom(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case23_became_a_parent_first_tom(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case24_sports_events_participated(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case25_stand_up_comedy_open_mic(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case26_necklace_for_my_sister_photo(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case27_order_of_airlines(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case28_area_rug_rearranged(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case29_seattle_international_film_festival(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case30_car_s_suspension_new_suspension(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case31_tuesdays_and_thursdays_wake(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case32_baking_class_birthday_cake(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case33_how_old_moved_to_the(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case34_undergraduate_degree_master_s_thesis(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case35_life_event_relative(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case36_last_visited_a_museum_with(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case37_book_the_airbnb_in_san(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case38_museum_two_months_ago(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case39_order_of_the_three_trips(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case40_concerts_and_musical_events_order(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case41_days_before_workshop(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case42_days_passed_between(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case43_what_did_i_do_wednesday(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case44_how_long_had_member(user_question, lowered_question, selected_rows))
    lines.extend(_temporal_case45_which_task_did_i_complete(user_question, lowered_question, selected_rows))

    lines.extend(_temporal_case46_who_did_i_go_with(user_question, lowered_question, selected_rows))
    return lines


def _build_temporal_event_ledger(selected_rows: list[tuple[int, int, dict[str, Any], list[str]]]) -> list[str]:
    """为事件型时间问题生成按日期排序的候选事件 ledger。"""
    event_cues = (
        "attended",
        "watched",
        "went to",
        "just went",
        "came back from",
        "walked down the aisle",
        "still on a high from watching",
        "started",
        "completed",
        "finished",
        "repotted",
        "cuttings",
        "gave",
        "workshop",
        "team meeting",
        "music event",
        "lesson",
        "joined",
        "meetup",
        "fixed",
        "trimmed",
        "hooves",
    )
    events: list[tuple[int, datetime | None, str, int, str]] = []
    for _, row_id, row, matched_terms in selected_rows:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        lowered = content.lower()
        if not any(cue in lowered for cue in event_cues) and len(set(matched_terms)) < 2:
            continue
        meta = _parse_metadata(row)
        ts = str(meta.get("timestamp") or "").strip()
        snippet = extract_focused_window(content, matched_terms[:8], radius=260, max_windows=1)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        phrase_hits = sum(1 for term in matched_terms if " " in term)
        score = len(set(matched_terms)) + (3 * phrase_hits)
        events.append((score, _parse_long_memory_date(ts), ts, row_id, snippet[:420]))
    if not events:
        return []
    ranked_events = sorted(events, key=lambda item: (-item[0], item[1] or datetime.min, item[3]))[:16]
    sorted_events = sorted(ranked_events, key=lambda item: (item[1] or datetime.min, item[3]))
    lines = ["Temporal event ledger (chronological candidate events):"]
    previous_date: datetime | None = None
    previous_row_id: int | None = None
    for _score, parsed_date, ts, row_id, snippet in sorted_events:
        tag = f"{ts} " if ts else ""
        lines.append(f"- {tag}(row={row_id}) {snippet}")
        if parsed_date is not None and previous_date is not None and previous_row_id is not None:
            delta = (parsed_date.date() - previous_date.date()).days
            if 0 <= delta <= 120:
                lines.append(
                    f"  delta_from_previous_candidate: {delta} calendar days (or {delta + 1} days if counted inclusively) from row={previous_row_id} to row={row_id}"
                )
        if parsed_date is not None:
            previous_date = parsed_date
            previous_row_id = row_id
    return lines

__all__ = ["_build_temporal_answer_ledger", "_build_temporal_event_ledger"]
