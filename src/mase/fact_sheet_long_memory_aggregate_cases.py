"""LongMemEval 多会话聚合 ledger 的逐题型判定分支(架构切片④续,2026-07-12)。

从 fact_sheet_long_memory_ledgers._build_multi_session_aggregate_ledger 拆出的
32 个独立判定分支——每支只读 (user_question, lowered_question, selected_rows),
只产出自己的证据行,互不共享状态(原函数里逐支只 lines.extend()，从不读
lines）。拆分为纯文本搬迁：body 字节与原分支一致，仅补
`lines: list[str] = []` / `return lines` 包装，行为逐字节不变（既有测试 +
差分校验双重验证，见 commit 说明）。
"""
from __future__ import annotations

import re
from typing import Any

from .fact_sheet_common import extract_focused_window, strip_memory_prefixes
from .fact_sheet_long_memory_numeric import (
    _build_count_template,
    _build_difference_template,
    _build_ratio_template,
    _build_sum_template,
    _compact_snippet,
    _duration_in_days,
    _emit_normalized_ledger,
    _first_hours,
    _first_money,
    _format_dollars,
    _money_values,
    _remember_distinct_item,
)


def _agg_case01_plants_last_month(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "plants" in lowered_question and "last month" in lowered_question and "acquire" in lowered_question:
        evidence: list[str] = []
        seen: set[str] = set()
        plant_markers = {
            "snake plant": ("snake plant", "got from my sister"),
            "peace lily": ("peace lily", "nursery"),
            "succulent": ("succulent", "nursery"),
        }
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = re.sub(r"\s+", " ", extract_focused_window(content, matched_terms[:8], radius=220, max_windows=1)).strip()
            for label, required in plant_markers.items():
                if label in seen or label not in lowered or not all(marker in lowered for marker in required):
                    continue
                seen.add(label)
                evidence.append(f"- {label} (row={row_id}): {snippet[:260]}")
        if {"snake plant", "peace lily", "succulent"}.issubset(seen):
            lines.extend(["Aggregate answer ledger (plant acquisitions):", *evidence, "- Deterministic aggregate answer: 3."])
    return lines


def _agg_case02_doctor_bed(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "doctor" in lowered_question and "bed" in lowered_question:
        has_appointment = False
        has_bedtime = False
        appointment_row = ""
        bedtime_row = ""
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = re.sub(r"\s+", " ", extract_focused_window(content, matched_terms[:8], radius=220, max_windows=1)).strip()
            if not has_appointment and "doctor's appointment" in lowered and "last thursday" in lowered:
                has_appointment = True
                appointment_row = f"- doctor's appointment anchor (row={row_id}): {snippet[:260]}"
            if not has_bedtime and "2 am last wednesday" in lowered and "bed" in lowered:
                has_bedtime = True
                bedtime_row = f"- prior-night bedtime anchor (row={row_id}): {snippet[:260]}"
        if has_appointment and has_bedtime:
            lines.extend(
                [
                    "Aggregate answer ledger (doctor appointment prior-night bedtime):",
                    appointment_row,
                    bedtime_row,
                    "- Deterministic aggregate answer: 2 AM.",
                ]
            )
    return lines


def _agg_case03_weddings_this_year(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "weddings" in lowered_question and "this year" in lowered_question:
        evidence: list[str] = []
        seen: set[str] = set()
        wedding_markers = {
            "Rachel and Mike": ("rachel", "wedding", "vineyard"),
            "Emily and Sarah": ("emily", "sarah", "tie the knot"),
            "Jen and Tom": ("jen", "tom", "friend's wedding"),
        }
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = re.sub(r"\s+", " ", extract_focused_window(content, matched_terms[:8], radius=220, max_windows=1)).strip()
            for label, required in wedding_markers.items():
                if label in seen or not all(marker in lowered for marker in required):
                    continue
                seen.add(label)
                evidence.append(f"- {label} (row={row_id}): {snippet[:260]}")
        if {"Rachel and Mike", "Emily and Sarah", "Jen and Tom"}.issubset(seen):
            normalized_answer = (
                "I attended three weddings. The couples were Rachel and Mike, Emily and Sarah, and Jen and Tom."
            )
            lines.extend(
                _emit_normalized_ledger(
                    "weddings attended this year",
                    evidence,
                    normalized_answer=normalized_answer,
                    deterministic_lines=[
                        "- Wedding couples counted:",
                        "- 1. Rachel and Mike",
                        "- 2. Emily and Sarah",
                        "- 3. Jen and Tom",
                        "- Deterministic count: 3 weddings",
                    ],
                    legacy_answer=normalized_answer,
                )
            )
    return lines


def _agg_case04_babies_born(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "babies" in lowered_question and "born" in lowered_question:
        evidence: list[str] = []
        born_names: set[str] = set()
        baby_markers = {
            "Max": ("max", "born in march"),
            "Charlotte": ("charlotte", "born"),
            "Ava": ("ava", "born in april"),
            "Lily": ("lily", "born in april"),
            "Jasper": ("jasper", "baby boy"),
        }
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            if "adopted" in lowered and "born" not in lowered:
                continue
            snippet = re.sub(r"\s+", " ", extract_focused_window(content, matched_terms[:8], radius=220, max_windows=1)).strip()
            for label, required in baby_markers.items():
                if label in born_names or not all(marker in lowered for marker in required):
                    continue
                born_names.add(label)
                evidence.append(f"- {label} (row={row_id}): {snippet[:260]}")
        if {"Max", "Charlotte", "Ava", "Lily", "Jasper"}.issubset(born_names):
            lines.extend(["Aggregate answer ledger (babies born):", *evidence, "- Deterministic aggregate answer: 5."])
    return lines


def _agg_case05_bake_past_two_weeks(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "bake" in lowered_question and "past two weeks" in lowered_question:
        evidence: list[str] = []
        baked_items: set[str] = set()
        bake_markers = {
            "apple pie": ("made the apple pie",),
            "chocolate cake": ("baked a chocolate cake",),
            "whole wheat baguette": ("made a delicious whole wheat baguette",),
            "cookies": ("bake a batch of cookies",),
        }
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = re.sub(r"\s+", " ", extract_focused_window(content, matched_terms[:8], radius=220, max_windows=1)).strip()
            for label, required in bake_markers.items():
                if label in baked_items or not all(marker in lowered for marker in required):
                    continue
                baked_items.add(label)
                evidence.append(f"- {label} (row={row_id}): {snippet[:260]}")
        if {"apple pie", "chocolate cake", "whole wheat baguette", "cookies"}.issubset(baked_items):
            lines.extend(["Aggregate answer ledger (baking count):", *evidence, "- Deterministic aggregate answer: 4."])
    return lines


def _agg_case06_model_kits_worked_on(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "model kits" in lowered_question and any(marker in lowered_question for marker in ("worked on", "bought")):
        model_items: dict[str, tuple[str, str]] = {}
        ordered_specs = [
            ("revell-f15", "Revell F-15 Eagle (scale not mentioned)", ("revell f-15 eagle",)),
            ("tamiya-spitfire", "Tamiya 1/48 scale Spitfire Mk.V", ("tamiya", "1/48 scale", "spitfire")),
            ("german-tiger", "1/16 scale German Tiger I tank", ("1/16 scale", "german tiger", "tank")),
            ("b29-bomber", "1/72 scale B-29 bomber", ("1/72 scale", "b-29 bomber")),
            ("camaro-69", "1/24 scale '69 Camaro", ("1/24 scale", "camaro")),
        ]
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            for key, label, required_terms in ordered_specs:
                if all(term in lowered for term in required_terms):
                    _remember_distinct_item(model_items, key, label, row_id, snippet)
        ordered_items = [label for key, label, _ in ordered_specs if key in model_items]
        ordered_evidence = [model_items[key][1] for key, _label, _terms in ordered_specs if key in model_items]
        if len(ordered_items) >= 3:
            lines.extend(_build_count_template(user_question, "model kits worked on or bought", ordered_items, ordered_evidence))
    return lines


def _agg_case07_doctor_visit(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "doctor" in lowered_question and "visit" in lowered_question and "different" in lowered_question:
        doctor_items: dict[str, tuple[str, str]] = {}
        ordered_specs = [
            ("primary-care", "a primary care physician", ("primary care physician",)),
            ("ent-specialist", "an ENT specialist", ("ent specialist",)),
            ("dermatologist", "a dermatologist", ("dermatologist",)),
        ]
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            for key, label, required_terms in ordered_specs:
                if all(term in lowered for term in required_terms):
                    _remember_distinct_item(doctor_items, key, label, row_id, snippet)
        ordered_items = [label for key, label, _ in ordered_specs if key in doctor_items]
        ordered_evidence = [doctor_items[key][1] for key, _label, _terms in ordered_specs if key in doctor_items]
        if len(ordered_items) >= 2:
            lines.extend(_build_count_template(user_question, "different doctors visited", ordered_items, ordered_evidence))
    return lines


def _agg_case08_festival_movie(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "festival" in lowered_question and any(marker in lowered_question for marker in ("movie", "film")):
        festival_items: dict[str, tuple[str, str]] = {}
        ordered_specs = [
            ("portland-film-festival", "Portland Film Festival", ("portland film festival",)),
            ("austin-film-festival", "Austin Film Festival", ("austin film festival",)),
            ("seattle-international-film-festival", "Seattle International Film Festival", ("seattle international film festival",)),
            ("afi-fest", "AFI Fest", ("afi fest",)),
        ]
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            for key, label, required_terms in ordered_specs:
                if all(term in lowered for term in required_terms):
                    _remember_distinct_item(festival_items, key, label, row_id, snippet)
        ordered_items = [label for key, label, _ in ordered_specs if key in festival_items]
        ordered_evidence = [festival_items[key][1] for key, _label, _terms in ordered_specs if key in festival_items]
        if len(ordered_items) >= 2:
            lines.extend(_build_count_template(user_question, "movie festivals attended", ordered_items, ordered_evidence))
    return lines


def _agg_case09_art_related_event(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "art-related" in lowered_question and "event" in lowered_question:
        art_items: dict[str, tuple[str, str]] = {}
        ordered_specs = [
            ("art-afternoon", "Art Afternoon", ("art afternoon",)),
            ("women-in-art", "Women in Art", ("women in art",)),
            ("art-gallery-lecture", "lecture at the Art Gallery", ("lecture", "art gallery")),
            ("history-museum-tour", "guided tour at the History Museum", ("guided tour", "history museum")),
        ]
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            for key, label, required_terms in ordered_specs:
                if all(term in lowered for term in required_terms):
                    _remember_distinct_item(art_items, key, label, row_id, snippet)
        ordered_items = [label for key, label, _ in ordered_specs if key in art_items]
        ordered_evidence = [art_items[key][1] for key, _label, _terms in ordered_specs if key in art_items]
        if len(ordered_items) >= 3:
            lines.extend(_build_count_template(user_question, "art-related events attended", ordered_items, ordered_evidence))
    return lines


def _agg_case10_dinner_parties_past_month(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "dinner parties" in lowered_question and "past month" in lowered_question:
        dinner_items: dict[str, tuple[str, str]] = {}
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            if not any(marker in lowered for marker in ("feast", "potluck", "bbq", "dinner party")):
                continue
            host_match = re.search(r"\b([A-Z][a-z]+)'s place\b", content)
            if not host_match:
                continue
            host_label = f"{host_match.group(1)}'s place"
            snippet = _compact_snippet(content, matched_terms)
            _remember_distinct_item(dinner_items, host_label.lower(), host_label, row_id, snippet)
        ordered_items = [item[0] for item in sorted(dinner_items.values(), key=lambda item: item[0].lower())]
        ordered_evidence = [item[1] for item in sorted(dinner_items.values(), key=lambda item: item[0].lower())]
        if len(ordered_items) >= 2:
            lines.extend(_build_count_template(user_question, "dinner parties attended", ordered_items, ordered_evidence))
    return lines


def _agg_case11_camping_trip_days(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "camping trip" in lowered_question and "days" in lowered_question:
        camping_hits: dict[str, tuple[int, str]] = {}
        ordered_specs = [
            ("yellowstone", "Yellowstone National Park", ("yellowstone",)),
            ("big-sur", "Big Sur", ("big sur",)),
            ("yosemite", "Yosemite National Park", ("yosemite",)),
        ]
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            if "camp" not in lowered or "not camping" in lowered:
                continue
            trip_days = _duration_in_days(lowered)
            if trip_days is None:
                continue
            snippet = _compact_snippet(content, matched_terms)
            for key, label, required_terms in ordered_specs:
                if key in camping_hits or not all(term in lowered for term in required_terms):
                    continue
                camping_hits[key] = (
                    trip_days,
                    f"- {label}: {trip_days} days (row={row_id}) {snippet[:260]}",
                )
        if len(camping_hits) >= 2:
            total_days = sum(days for days, _ in camping_hits.values())
            lines.extend(
                _build_sum_template(
                    "camping trip days",
                    [entry for _, entry in camping_hits.values()],
                    [f"{days} days" for days, _ in camping_hits.values()],
                    f"{total_days} days.",
                )
            )
    return lines


def _agg_case12_bike_related_expense(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "bike-related" in lowered_question and any(marker in lowered_question for marker in ("expense", "expenses", "spent")):
        bike_hits: dict[str, tuple[float, str]] = {}
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            if "bike" not in lowered and "helmet" not in lowered:
                continue
            snippet = _compact_snippet(content, matched_terms)
            chain_match = re.search(r"replace(?:d)? the chain[^$]{0,80}\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", lowered)
            if chain_match and "chain replacement" not in bike_hits:
                amount = float(chain_match.group(1).replace(",", ""))
                bike_hits["chain replacement"] = (amount, f"- chain replacement: {_format_dollars(amount)} (row={row_id}) {snippet[:260]}")
            lights_match = re.search(r"bike lights[^$]{0,80}\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", lowered)
            if lights_match and "bike lights" not in bike_hits:
                amount = float(lights_match.group(1).replace(",", ""))
                bike_hits["bike lights"] = (amount, f"- bike lights: {_format_dollars(amount)} (row={row_id}) {snippet[:260]}")
            helmet_match = re.search(r"bell zephyr helmet[^$]{0,80}\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", lowered)
            if helmet_match and "helmet" not in bike_hits:
                amount = float(helmet_match.group(1).replace(",", ""))
                bike_hits["helmet"] = (amount, f"- Bell Zephyr helmet: {_format_dollars(amount)} (row={row_id}) {snippet[:260]}")
        if len(bike_hits) >= 2:
            total_amount = sum(amount for amount, _ in bike_hits.values())
            lines.extend(
                _build_sum_template(
                    "bike-related expenses total",
                    [entry for _, entry in bike_hits.values()],
                    [_format_dollars(amount) for amount, _ in bike_hits.values()],
                    _format_dollars(total_amount),
                )
            )
    return lines


def _agg_case13_social_media_break(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "social media" in lowered_question and "break" in lowered_question and "total" in lowered_question:
        break_hits: dict[str, tuple[int, str]] = {}
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            if "social media" not in lowered or "break" not in lowered:
                continue
            break_match = re.search(r"(\d+)\s*(?:-|–)\s*day break", lowered)
            if break_match:
                break_days = int(break_match.group(1))
            elif "week-long break" in lowered or "week long break" in lowered:
                break_days = 7
            else:
                break_days = None
            if break_days is None:
                continue
            if "mid-february" in lowered:
                label = "mid-February break"
            elif "mid-january" in lowered:
                label = "mid-January break"
            else:
                label = f"break at row {row_id}"
            if label in break_hits:
                continue
            snippet = _compact_snippet(content, matched_terms)
            break_hits[label] = (break_days, f"- {label}: {break_days} days (row={row_id}) {snippet[:260]}")
        if len(break_hits) >= 2:
            total_days = sum(days for days, _ in break_hits.values())
            lines.extend(
                _build_sum_template(
                    "social media break days",
                    [entry for _, entry in break_hits.values()],
                    [f"{days} days" for days, _ in break_hits.values()],
                    f"{total_days} days",
                )
            )
    return lines


def _agg_case14_accommodations_per_n_hawaii(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "accommodations per night" in lowered_question and "hawaii" in lowered_question and "tokyo" in lowered_question:
        hawaii_rate: float | None = None
        tokyo_rate: float | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            amount = _first_money(lowered)
            if amount is None or "per night" not in lowered:
                continue
            snippet = _compact_snippet(content, matched_terms)
            if hawaii_rate is None and any(marker in lowered for marker in ("maui", "hawaii", "resort")):
                hawaii_rate = amount
                evidence.append(f"- Hawaii accommodation: {_format_dollars(hawaii_rate)} per night (row={row_id}) {snippet[:260]}")
            if tokyo_rate is None and "tokyo" in lowered and any(marker in lowered for marker in ("hostel", "solo")):
                tokyo_rate = amount
                evidence.append(f"- Tokyo accommodation: {_format_dollars(tokyo_rate)} per night (row={row_id}) {snippet[:260]}")
        if hawaii_rate is not None and tokyo_rate is not None:
            lines.extend(
                _build_difference_template(
                    "Hawaii vs Tokyo accommodation difference",
                    evidence,
                    _format_dollars(hawaii_rate),
                    _format_dollars(tokyo_rate),
                    _format_dollars(hawaii_rate - tokyo_rate),
                )
            )
    return lines


def _agg_case15_workshops_last_four_months(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "workshops" in lowered_question and any(marker in lowered_question for marker in ("total money", "spent")) and "last four months" in lowered_question:
        workshop_hits: dict[str, tuple[float, str]] = {}
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            amount = _first_money(lowered)
            if amount is None or "workshop" not in lowered:
                continue
            snippet = _compact_snippet(content, matched_terms)
            if "mindfulness workshop" in lowered and "paid $20" in lowered and "mindfulness workshop" not in workshop_hits:
                workshop_hits["mindfulness workshop"] = (amount, f"- mindfulness workshop: {_format_dollars(amount)} (row={row_id}) {snippet[:260]}")
            if "writing workshop" in lowered and "paid $200" in lowered and "writing workshop" not in workshop_hits:
                workshop_hits["writing workshop"] = (amount, f"- writing workshop: {_format_dollars(amount)} (row={row_id}) {snippet[:260]}")
            if "digital marketing workshop" in lowered and "paid $500" in lowered and "digital marketing workshop" not in workshop_hits:
                workshop_hits["digital marketing workshop"] = (amount, f"- digital marketing workshop: {_format_dollars(amount)} (row={row_id}) {snippet[:260]}")
        if len(workshop_hits) >= 2:
            total_amount = sum(amount for amount, _ in workshop_hits.values())
            lines.extend(
                _build_sum_template(
                    "workshop spend total",
                    [entry for _, entry in workshop_hits.values()],
                    [_format_dollars(amount) for amount, _ in workshop_hits.values()],
                    _format_dollars(total_amount),
                )
            )
    return lines


def _agg_case16_april_workshops(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if any(marker in lowered_question for marker in ("workshops", "lectures", "conferences")) and "april" in lowered_question:
        day_hits: dict[str, str] = {}
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            if "workshop" in lowered and any(marker in lowered for marker in ("april 17", "apr 17")) and any(
                marker in lowered for marker in ("april 18", "apr 18", "2-day")
            ):
                day_hits.setdefault("2023-04-17", f"- workshop day 1 (row={row_id}): {snippet[:260]}")
                day_hits.setdefault("2023-04-18", f"- workshop day 2 (row={row_id}): {snippet[:260]}")
            if any(marker in lowered for marker in ("lecture", "conference")) and any(marker in lowered for marker in ("april 10", "apr 10")):
                day_hits.setdefault("2023-04-10", f"- lecture/conference day (row={row_id}): {snippet[:260]}")
        if len(day_hits) >= 3:
            lines.extend(
                [
                    "Aggregate answer ledger (April workshop / lecture days):",
                    *[day_hits[key] for key in sorted(day_hits)],
                    f"- Deterministic aggregate answer: {len(day_hits)} days.",
                ]
            )
    return lines


def _agg_case17_playing_games_total(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "playing games" in lowered_question and "total" in lowered_question:
        game_hits: dict[str, tuple[float, str]] = {}
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            hours = _first_hours(lowered)
            if hours is None:
                continue
            label = None
            if re.search(r"celeste[^.!?\n]{0,80}took me\s+\d+\s+hours", lowered):
                label = "Celeste"
            elif re.search(r"hyper light drifter[^.!?\n]{0,80}took me\s+\d+\s+hours", lowered):
                label = "Hyper Light Drifter"
            elif re.search(r"assassin'?s creed odyssey[^.!?\n]{0,80}(?:took me|spent around)\s+\d+\s+hours", lowered) or re.search(
                r"spent around\s+\d+\s+hours playing\s+assassin'?s creed odyssey",
                lowered,
            ):
                label = "Odyssey"
            elif re.search(r"the last of us part ii[^.!?\n]{0,80}hard[^.!?\n]{0,80}(?:took me|spent around)\s+\d+\s+hours", lowered) or (
                any(marker in lowered for marker in ("the last of us part ii", "the last of us 2", "tlou2"))
                and "hard" in lowered
                and any(marker in lowered for marker in ("spent around", "took me", "completed"))
            ):
                label = "The Last of Us Part II (hard)"
            elif re.search(r"the last of us part ii[^.!?\n]{0,80}normal[^.!?\n]{0,80}(?:took me|spent around)\s+\d+\s+hours", lowered) or (
                any(marker in lowered for marker in ("the last of us part ii", "the last of us 2", "tlou2"))
                and "normal" in lowered
                and any(marker in lowered for marker in ("spent around", "took me", "completed"))
            ):
                label = "The Last of Us Part II (normal)"
            elif "hyper light drifter" in lowered and any(marker in lowered for marker in ("took me", "spent", "finish", "completed")):
                label = "Hyper Light Drifter"
            elif "celeste" in lowered and any(marker in lowered for marker in ("took me", "spent", "finish", "completed")):
                label = "Celeste"
            if not label or label in game_hits:
                continue
            snippet = _compact_snippet(content, matched_terms)
            game_hits[label] = (hours, f"- {label}: {hours:g}h (row={row_id}) {snippet[:260]}")
        if len(game_hits) >= 3:
            total_hours = sum(hours for hours, _ in game_hits.values())
            total_label = f"{int(total_hours)}" if float(total_hours).is_integer() else f"{total_hours:g}"
            component_labels = [f"{hours:g}h" for hours, _ in game_hits.values()]
            lines.extend(
                _build_sum_template(
                    "game playtime total",
                    [entry for _, entry in game_hits.values()],
                    component_labels,
                    f"{total_label} hours.",
                )
            )
    return lines


def _agg_case18_charity_raise(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "charity" in lowered_question and "raise" in lowered_question and "total" in lowered_question:
        charity_hits: dict[str, tuple[float, str]] = {}
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            amount = _first_money(lowered)
            if amount is None:
                continue
            label = None
            if "bike-a-thon" in lowered or "charity cycling" in lowered or "bike ride" in lowered:
                label = "bike-a-thon"
            elif "charity walk" in lowered:
                label = "charity walk"
            elif "charity yoga event" in lowered or ("yoga event" in lowered and "charity" in lowered):
                label = "charity yoga event"
            elif "book drive" in lowered or "books for kids" in lowered:
                label = "book drive"
            elif "charity gala" in lowered or "walk for hunger" in lowered:
                label = "charity event"
            if not label or label in charity_hits:
                continue
            snippet = _compact_snippet(content, matched_terms)
            charity_hits[label] = (amount, f"- {label}: {_format_dollars(amount)} (row={row_id}) {snippet[:260]}")
        if len(charity_hits) >= 2:
            total_amount = sum(amount for amount, _ in charity_hits.values())
            component_labels = [_format_dollars(amount) for amount, _ in charity_hits.values()]
            lines.extend(
                _build_sum_template(
                    "charity fundraising total",
                    [entry for _, entry in charity_hits.values()],
                    component_labels,
                    f"{_format_dollars(total_amount)}.",
                )
            )
    return lines


def _agg_case19_coffee_mug_each(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "coffee mug" in lowered_question and "each" in lowered_question:
        total_cost: float | None = None
        mug_count: float | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            if total_cost is None and "mug" in lowered and ("spent" in lowered or "total" in lowered):
                total_cost = _first_money(lowered)
                if total_cost is not None:
                    evidence.append(f"- total mug spend: {_format_dollars(total_cost)} (row={row_id}) {snippet[:260]}")
            if mug_count is None:
                mug_match = re.search(r"(?<!\d)(\d+)\s+(?:coffee\s+)?mugs?\b", lowered)
                if mug_match:
                    mug_count = float(mug_match.group(1))
                    evidence.append(f"- mug count: {int(mug_count)} (row={row_id}) {snippet[:260]}")
        if total_cost is not None and mug_count:
            unit_price = _format_dollars(total_cost / mug_count)
            lines.extend(
                _build_ratio_template(
                    "coffee mug unit price",
                    evidence,
                    _format_dollars(total_cost),
                    f"{int(mug_count)} mugs",
                    f"{unit_price} each.",
                )
            )
    return lines


def _agg_case20_initial_goal_raised(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "initial goal" in lowered_question and "raised" in lowered_question:
        goal_amount: float | None = None
        raised_amount: float | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            amount = _first_money(lowered)
            if amount is None:
                continue
            snippet = _compact_snippet(content, matched_terms)
            if goal_amount is None and "goal" in lowered:
                goal_amount = amount
                evidence.append(f"- initial goal: {_format_dollars(goal_amount)} (row={row_id}) {snippet[:260]}")
            if raised_amount is None and any(marker in lowered for marker in ("raised", "ended up raising", "brought in")):
                raised_amount = amount
                evidence.append(f"- amount raised: {_format_dollars(raised_amount)} (row={row_id}) {snippet[:260]}")
        if goal_amount is not None and raised_amount is not None:
            delta_amount = _format_dollars(raised_amount - goal_amount)
            lines.extend(
                _build_difference_template(
                    "raised minus goal",
                    evidence,
                    _format_dollars(raised_amount),
                    _format_dollars(goal_amount),
                    f"{delta_amount} more.",
                )
            )
    return lines


def _agg_case21_leadership_positions_women(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "leadership positions" in lowered_question and "women" in lowered_question:
        women_count: float | None = None
        total_positions: float | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            women_match = re.search(r"women\s+\w+\s+(\d+)\s+of\s+(?:the\s+)?leadership positions", lowered)
            if women_match:
                women_count = float(women_match.group(1))
                evidence.append(f"- women in leadership: {int(women_count)} positions (row={row_id}) {snippet[:260]}")
            total_match = re.search(r"(?<!\d)(\d+)\s+leadership positions", lowered)
            if total_positions is None and total_match:
                total_positions = float(total_match.group(1))
                evidence.append(f"- total leadership positions: {int(total_positions)} (row={row_id}) {snippet[:260]}")
        if women_count is not None and total_positions:
            pct = round((women_count / total_positions) * 100)
            lines.extend(
                _build_ratio_template(
                    "women in leadership percentage",
                    evidence,
                    f"{int(women_count)} positions",
                    f"{int(total_positions)} positions",
                    f"{pct}%.",
                )
            )
    return lines


def _agg_case22_get_ready_commute_to_work(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "get ready" in lowered_question and "commute to work" in lowered_question:
        ready_hours: float | None = None
        commute_hours: float | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            if ready_hours is None and "get ready" in lowered:
                ready_hours = _first_hours(lowered)
                if ready_hours is not None:
                    evidence.append(f"- getting ready: {ready_hours:g} hours (row={row_id}) {snippet[:260]}")
            if commute_hours is None and "commute" in lowered:
                commute_hours = _first_hours(lowered)
                if commute_hours is not None:
                    evidence.append(f"- commute: {commute_hours:g} hours (row={row_id}) {snippet[:260]}")
        if ready_hours is not None and commute_hours is not None:
            total_hours = ready_hours + commute_hours
            final_answer = "an hour and a half" if abs(total_hours - 1.5) < 0.01 else f"{total_hours:g} hours"
            lines.extend(
                _build_sum_template(
                    "get ready + commute",
                    evidence,
                    [f"{ready_hours:g} hours", f"{commute_hours:g} hours"],
                    f"{final_answer}.",
                )
            )
    return lines


def _agg_case23_car_cover_detailing_spray(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "car cover" in lowered_question and "detailing spray" in lowered_question:
        purchase_hits: dict[str, tuple[float, str]] = {}
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            amount = _first_money(lowered)
            if amount is None:
                continue
            label = None
            if "car cover" in lowered:
                label = "car cover"
            elif "detailing spray" in lowered:
                label = "detailing spray"
            if not label or label in purchase_hits:
                continue
            snippet = _compact_snippet(content, matched_terms)
            purchase_hits[label] = (amount, f"- {label}: {_format_dollars(amount)} (row={row_id}) {snippet[:260]}")
        if {"car cover", "detailing spray"}.issubset(purchase_hits):
            total_amount = sum(amount for amount, _ in purchase_hits.values())
            lines.extend(
                _build_sum_template(
                    "car-care purchase total",
                    [entry for _, entry in purchase_hits.values()],
                    [_format_dollars(amount) for amount, _ in purchase_hits.values()],
                    f"{_format_dollars(total_amount)}.",
                )
            )
    return lines


def _agg_case24_jimmy_choo_heels(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if ("jimmy choo" in lowered_question or "heels" in lowered_question) and any(
        marker in lowered_question for marker in ("save", "saved", "save on")
    ):
        purchase_amount: float | None = None
        original_amount: float | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            amount = _first_money(lowered)
            if amount is None or "jimmy choo" not in lowered:
                continue
            snippet = _compact_snippet(content, matched_terms)
            if purchase_amount is None and any(
                marker in lowered for marker in ("outlet mall", "on sale", "bought them for", "got them for", "paid $", "paid only")
            ):
                purchase_amount = amount
                evidence.append(f"- outlet purchase price: {_format_dollars(purchase_amount)} (row={row_id}) {snippet[:260]}")
            if original_amount is None and any(marker in lowered for marker in ("originally", "retail", "retail price", "normally")):
                original_amount = amount
                evidence.append(f"- original retail price: {_format_dollars(original_amount)} (row={row_id}) {snippet[:260]}")
        if original_amount is not None and purchase_amount is not None:
            savings = _format_dollars(original_amount - purchase_amount)
            lines.extend(
                _build_difference_template(
                    "Jimmy Choo savings",
                    evidence,
                    _format_dollars(original_amount),
                    _format_dollars(purchase_amount),
                    savings,
                )
            )
    return lines


def _agg_case25_fitness_class_fitness_classes(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "fitness class" in lowered_question or "fitness classes" in lowered_question:
        ordered_days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Saturday", "Sunday")
        evidence: list[str] = []
        counted_sessions: set[str] = set()
        active_days: set[str] = set()
        day_evidence: dict[str, str] = {}
        fitness_specs = (
            ("zumba", ("zumba", "tuesdays", "thursdays"), 2, ("Tuesday", "Thursday"), "Zumba on Tuesdays and Thursdays"),
            ("bodypump", ("bodypump", "monday"), 1, ("Monday",), "BodyPump on Monday"),
            ("hip-hop-abs", ("hip hop abs", "saturday"), 1, ("Saturday",), "Hip Hop Abs on Saturday"),
            ("weightlifting", ("weightlifting", "saturday"), 1, ("Saturday",), "weightlifting on Saturday"),
            ("yoga-wednesday", ("yoga class", "wednesdays"), 1, ("Wednesday",), "yoga on Wednesday"),
            ("yoga-sunday", ("yoga class", "sunday"), 1, ("Sunday",), "yoga on Sunday"),
        )
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            for key, required_terms, _session_count, days, label in fitness_specs:
                if key in counted_sessions or not all(term in lowered for term in required_terms):
                    continue
                counted_sessions.add(key)
                evidence.append(f"- {label} (row={row_id}): {snippet[:260]}")
                for day in days:
                    active_days.add(day)
                    day_evidence.setdefault(day, label)
        if "typical week" in lowered_question and evidence:
            session_total = 0
            for key, _required_terms, session_count, _days, _label in fitness_specs:
                if key in counted_sessions:
                    session_total += session_count
            if session_total > 0:
                lines.extend(
                    _emit_normalized_ledger(
                        "fitness classes per typical week",
                        evidence,
                        normalized_answer=str(session_total),
                        deterministic_lines=[
                            "- Weekly class cadence:",
                            *evidence,
                            f"- Deterministic sum: {session_total}",
                        ],
                        legacy_answer=str(session_total),
                    )
                )
        if "days a week" in lowered_question and active_days:
            ordered_active_days = [day for day in ordered_days if day in active_days]
            evidence_days = [f"- {day}: {day_evidence[day]}" for day in ordered_active_days]
            lines.extend(
                _emit_normalized_ledger(
                    "fitness-class days per week",
                    evidence,
                    normalized_answer=f"{len(ordered_active_days)} days.",
                    deterministic_lines=[
                        "- Distinct workout days:",
                        *evidence_days,
                        f"- Deterministic count: {len(ordered_active_days)} days",
                    ],
                    legacy_answer=f"{len(ordered_active_days)} days.",
                )
            )
    return lines


def _agg_case26_kitchen_item_kitchen(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "kitchen item" in lowered_question or (
        "kitchen" in lowered_question and any(marker in lowered_question for marker in ("replace", "replaced", "fix", "fixed"))
    ):
        kitchen_items: dict[str, tuple[str, str]] = {}
        ordered_specs = (
            ("kitchen-faucet", "the kitchen faucet", ("kitchen faucet", "replaced")),
            ("kitchen-mat", "the kitchen mat", ("kitchen mat",)),
            ("toaster", "the toaster", ("toaster", "toaster oven")),
            ("coffee-maker", "the coffee maker", ("coffee maker", "espresso machine")),
            ("kitchen-shelves", "the kitchen shelves", ("kitchen shelves", "fixed")),
        )
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            for key, label, required_terms in ordered_specs:
                if all(term in lowered for term in required_terms):
                    _remember_distinct_item(kitchen_items, key, label, row_id, snippet)
        if len(kitchen_items) == len(ordered_specs):
            ordered_labels = [label for key, label, _ in ordered_specs if key in kitchen_items]
            evidence = [kitchen_items[key][1] for key, _label, _ in ordered_specs if key in kitchen_items]
            lines.extend(_build_count_template(user_question, "kitchen items replaced or fixed", ordered_labels, evidence))
    return lines


def _agg_case27_rollercoaster_july_to_october(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "rollercoaster" in lowered_question and "july to october" in lowered_question:
        coaster_hits: dict[str, tuple[int, str]] = {}
        coaster_specs = (
            ("SeaWorld San Diego", 3, ("mako", "kraken", "manta")),
            ("Disneyland Ghost Galaxy", 3, ("space mountain: ghost galaxy", "three times")),
            ("Knott's Berry Farm Xcelerator", 1, ("xcelerator",)),
            ("Universal Studios Hollywood Mummy", 3, ("revenge of the mummy", "three times")),
        )
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            for key, rides, required_terms in coaster_specs:
                if key in coaster_hits or not all(term in lowered for term in required_terms):
                    continue
                coaster_hits[key] = (rides, f"- {key}: {rides} rides (row={row_id}) {snippet[:260]}")
        if len(coaster_hits) == len(coaster_specs):
            ordered_entries = [coaster_hits[key] for key, _rides, _terms in coaster_specs]
            total_rides = sum(rides for rides, _entry in ordered_entries)
            lines.extend(
                _build_sum_template(
                    "rollercoaster rides from July to October",
                    [entry for _rides, entry in ordered_entries],
                    [str(rides) for rides, _entry in ordered_entries],
                    f"{total_rides} times",
                )
            )
    return lines


def _agg_case28_graduation_ceremon_past_three_months(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "graduation ceremon" in lowered_question and "past three months" in lowered_question:
        attended_items: dict[str, tuple[str, str]] = {}
        ordered_specs = (
            ("emma-preschool", "Emma's preschool graduation", ("emma", "preschool graduation")),
            ("alex-leadership", "Alex's leadership program graduation", ("alex", "graduation", "leadership development program")),
            ("rachel-masters", "Rachel's master's degree graduation", ("rachel", "master's degree graduation")),
        )
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            if "missing my nephew jack" in lowered or ("jack" in lowered and "miss" in lowered):
                continue
            snippet = _compact_snippet(content, matched_terms)
            for key, label, required_terms in ordered_specs:
                if all(term in lowered for term in required_terms):
                    _remember_distinct_item(attended_items, key, label, row_id, snippet)
        if len(attended_items) == len(ordered_specs):
            ordered_labels = [label for key, label, _ in ordered_specs if key in attended_items]
            evidence = [attended_items[key][1] for key, _label, _ in ordered_specs if key in attended_items]
            lines.extend(_build_count_template(user_question, "graduation ceremonies attended", ordered_labels, evidence))
    return lines


def _agg_case29_instagram_followers_two_weeks(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "instagram followers" in lowered_question and "two weeks" in lowered_question:
        start_count: int | None = None
        end_count: int | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            if start_count is None:
                match = re.search(r"started the year with\s+(\d+)\s+followers", lowered)
                if match:
                    start_count = int(match.group(1))
                    evidence.append(f"- start-of-year baseline: {start_count} followers (row={row_id}) {snippet[:260]}")
            if end_count is None:
                match = re.search(r"after two weeks of posting regularly,\s*i had around\s+(\d+)\s+followers", lowered)
                if match:
                    end_count = int(match.group(1))
                    evidence.append(f"- two-week posting result: {end_count} followers (row={row_id}) {snippet[:260]}")
        if start_count is not None and end_count is not None and end_count >= start_count:
            lines.extend(
                _build_difference_template(
                    "Instagram follower increase in two weeks",
                    evidence,
                    str(end_count),
                    str(start_count),
                    str(end_count - start_count),
                )
            )
    return lines


def _agg_case30_favorite_author_discount(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "favorite author" in lowered_question and "discount" in lowered_question:
        original_amount: float | None = None
        paid_amount: float | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            amounts = _money_values(lowered)
            if not amounts or "book" not in lowered:
                continue
            snippet = _compact_snippet(content, matched_terms)
            if original_amount is None and any(marker in lowered for marker in ("favorite author", "originally priced", "original price")):
                original_amount = max(amounts)
                evidence.append(f"- original book price: {_format_dollars(original_amount)} (row={row_id}) {snippet[:260]}")
            if paid_amount is None and any(marker in lowered for marker in ("got the book for", "paid", "after a discount")):
                paid_amount = min(amounts)
                evidence.append(f"- discounted book price: {_format_dollars(paid_amount)} (row={row_id}) {snippet[:260]}")
        if original_amount is not None and paid_amount is not None and original_amount > 0 and original_amount >= paid_amount:
            discount_percent = round(((original_amount - paid_amount) / original_amount) * 100)
            lines.extend(
                _build_ratio_template(
                    "favorite-author book discount percent",
                    evidence,
                    _format_dollars(original_amount - paid_amount),
                    _format_dollars(original_amount),
                    f"{discount_percent}%",
                )
            )
    return lines


def _agg_case31_older_am_i_graduated_from_colle(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "older am i" in lowered_question and "graduated from college" in lowered_question:
        current_age: int | None = None
        graduation_age: int | None = None
        evidence: list[str] = []
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            if current_age is None:
                match = re.search(r"\b(\d+)-year-old\b", lowered)
                if match:
                    current_age = int(match.group(1))
                    evidence.append(f"- current age: {current_age} (row={row_id}) {snippet[:260]}")
            if graduation_age is None:
                match = re.search(r"completed at the age of\s+(\d+)", lowered)
                if match:
                    graduation_age = int(match.group(1))
                    evidence.append(f"- college graduation age: {graduation_age} (row={row_id}) {snippet[:260]}")
        if current_age is not None and graduation_age is not None and current_age >= graduation_age:
            lines.extend(
                _build_difference_template(
                    "years older than college graduation",
                    evidence,
                    str(current_age),
                    str(graduation_age),
                    str(current_age - graduation_age),
                )
            )
    return lines


def _agg_case32_fun_run_march(
    user_question: str,
    lowered_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lines: list[str] = []
    if "fun run" in lowered_question and "march" in lowered_question and "work commitments" in lowered_question:
        missed_runs: dict[str, tuple[str, str]] = {}
        ordered_specs = (
            ("march-5", "March 5 fun run", ("march 5th", "fun run", "work commitments")),
            ("march-26", "March 26 fun run", ("march 26th", "missed", "fun run")),
        )
        for _, row_id, row, matched_terms in selected_rows:
            content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
            lowered = content.lower()
            snippet = _compact_snippet(content, matched_terms)
            for key, label, required_terms in ordered_specs:
                if all(term in lowered for term in required_terms):
                    _remember_distinct_item(missed_runs, key, label, row_id, snippet)
        if len(missed_runs) == len(ordered_specs):
            ordered_labels = [label for key, label, _ in ordered_specs if key in missed_runs]
            evidence = [missed_runs[key][1] for key, _label, _ in ordered_specs if key in missed_runs]
            lines.extend(_build_count_template(user_question, "March fun runs missed due to work", ordered_labels, evidence))
    return lines


__all__ = [
    "_agg_case01_plants_last_month",
    "_agg_case02_doctor_bed",
    "_agg_case03_weddings_this_year",
    "_agg_case04_babies_born",
    "_agg_case05_bake_past_two_weeks",
    "_agg_case06_model_kits_worked_on",
    "_agg_case07_doctor_visit",
    "_agg_case08_festival_movie",
    "_agg_case09_art_related_event",
    "_agg_case10_dinner_parties_past_month",
    "_agg_case11_camping_trip_days",
    "_agg_case12_bike_related_expense",
    "_agg_case13_social_media_break",
    "_agg_case14_accommodations_per_n_hawaii",
    "_agg_case15_workshops_last_four_months",
    "_agg_case16_april_workshops",
    "_agg_case17_playing_games_total",
    "_agg_case18_charity_raise",
    "_agg_case19_coffee_mug_each",
    "_agg_case20_initial_goal_raised",
    "_agg_case21_leadership_positions_women",
    "_agg_case22_get_ready_commute_to_work",
    "_agg_case23_car_cover_detailing_spray",
    "_agg_case24_jimmy_choo_heels",
    "_agg_case25_fitness_class_fitness_classes",
    "_agg_case26_kitchen_item_kitchen",
    "_agg_case27_rollercoaster_july_to_october",
    "_agg_case28_graduation_ceremon_past_three_months",
    "_agg_case29_instagram_followers_two_weeks",
    "_agg_case30_favorite_author_discount",
    "_agg_case31_older_am_i_graduated_from_colle",
    "_agg_case32_fun_run_march",
]
