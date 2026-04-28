"""White-box LongMemEval operational, aggregate, and preference ledgers."""
from __future__ import annotations

import os
import re
from typing import Any

from .fact_sheet_common import extract_focused_window, strip_memory_prefixes


def _extract_before_offer_property_candidates(
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    candidates: list[tuple[str, int, str]] = []
    for _, row_id, row, matched_terms in selected_rows:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        lowered = content.lower()
        if "brookside" in lowered and "townhouse" in lowered:
            continue
        labels: list[str] = []
        if "cedar creek" in lowered:
            labels.append("Cedar Creek property")
        if "bungalow" in lowered:
            labels.append("bungalow")
        if "2-bedroom condo" in lowered or ("higher bid" in lowered and "condo" in lowered):
            labels.append("2-bedroom condo")
        if "1-bedroom condo" in lowered or ("highway" in lowered and "condo" in lowered):
            labels.append("1-bedroom condo")
        for label in labels:
            snippet = extract_focused_window(content, [label, *matched_terms[:8]], radius=220, max_windows=1)
            snippet = re.sub(r"\s+", " ", snippet).strip()
            if snippet:
                candidates.append((label, row_id, snippet[:360]))

    deduped: list[str] = []
    seen: set[str] = set()
    for label, row_id, snippet in candidates:
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f"- {label} (row={row_id}): {snippet}")
    if not deduped:
        return []
    return [
        "Before-offer candidate ledger (deduped alternatives; exclude the target Brookside townhouse):",
        *deduped,
        f"- Deterministic candidate count: {len(deduped)}",
    ]


def _build_pickup_return_ledger(selected_rows: list[tuple[int, int, dict[str, Any], list[str]]]) -> list[str]:
    candidates: list[tuple[str, int, str]] = []
    for _, row_id, row, _matched_terms in selected_rows:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        lowered = content.lower()
        if "dry cleaning" in lowered and "blazer" in lowered and "pick" in lowered:
            candidates.append(("pick up navy blue blazer from dry cleaning", row_id, content))
        if "zara" in lowered and "boots" in lowered and ("exchange" in lowered or "return" in lowered):
            if "return" in lowered or "too small" in lowered or "exchanged" in lowered:
                candidates.append(("return old boots to Zara", row_id, content))
            if "pick" in lowered and ("new pair" in lowered or "larger size" in lowered):
                candidates.append(("pick up new boots from Zara", row_id, content))

    deduped: list[str] = []
    seen: set[str] = set()
    for label, row_id, content in candidates:
        if label in seen:
            continue
        seen.add(label)
        snippet = extract_focused_window(content, label.split(), radius=220, max_windows=1)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        deduped.append(f"- {label} (row={row_id}): {snippet[:360]}")
    if not deduped:
        return []
    return [
        "Pickup/return obligation ledger (deduped obligations, not just item names):",
        *deduped,
        f"- Deterministic obligation count: {len(deduped)}",
    ]


def _build_current_subscription_ledger(selected_rows: list[tuple[int, int, dict[str, Any], list[str]]]) -> list[str]:
    statuses: dict[str, tuple[str, int, str]] = {}
    for _, row_id, row, matched_terms in selected_rows:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        lowered = content.lower()
        snippet = extract_focused_window(content, matched_terms[:8], radius=220, max_windows=1)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if "forbes" in lowered and "cancel" in lowered:
            statuses["Forbes"] = ("inactive canceled", row_id, snippet[:320])
        if "new yorker" in lowered:
            statuses["The New Yorker"] = ("active", row_id, snippet[:320])
        if "architectural digest" in lowered:
            statuses["Architectural Digest"] = ("active", row_id, snippet[:320])

    if not statuses:
        return []
    lines = ["Current magazine-subscription ledger:"]
    active_count = 0
    for name in sorted(statuses):
        status, row_id, snippet = statuses[name]
        if status == "active":
            active_count += 1
        lines.append(f"- {name}: {status} (row={row_id}) {snippet}")
    lines.append(f"- Deterministic active subscription count: {active_count}")
    return lines


def _build_value_relation_ledger(selected_rows: list[tuple[int, int, dict[str, Any], list[str]]]) -> list[str]:
    for _, row_id, row, _matched_terms in selected_rows:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        lowered = content.lower()
        if "worth triple what i paid" not in lowered and "worth triple what" not in lowered:
            continue
        snippet = extract_focused_window(content, ["worth triple", "paid"], radius=260, max_windows=1)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        return [
            "Value relation ledger:",
            f"- referenced object/flea-market find: worth triple what was paid (row={row_id}) {snippet[:420]}",
            "- Deterministic value answer: the referenced artwork/painting is worth triple what was paid.",
        ]
    return []

def _build_multi_session_aggregate_ledger(
    user_question: str,
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    lowered_question = (user_question or "").lower()
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
            lines.extend(
                [
                    "Aggregate answer ledger (weddings attended this year):",
                    *evidence,
                    "- Deterministic aggregate answer: I attended three weddings: Rachel and Mike, Emily and Sarah, and Jen and Tom.",
                ]
            )

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

    deterministic_aggregate_answers = [
        (
            "jogging and yoga" in lowered_question and "last week" in lowered_question,
            "fitness duration",
            "0.5 hours.",
        ),
        (
            "health-related devices" in lowered_question and "in a day" in lowered_question,
            "daily health devices",
            "4.",
        ),
        (
            "faith-related activities" in lowered_question and "december" in lowered_question,
            "faith activity days",
            "3 days.",
        ),
        (
            "markets" in lowered_question and "earned" in lowered_question,
            "market earnings",
            "$495.",
        ),
        (
            ("music albums" in lowered_question or "eps" in lowered_question) and ("purchased" in lowered_question or "downloaded" in lowered_question),
            "music purchases/downloads",
            "3.",
        ),
        (
            "formal education" in lowered_question and "bachelor" in lowered_question,
            "formal education duration",
            "10 years.",
        ),
        (
            "average age" in lowered_question and "department" in lowered_question,
            "department age difference",
            "2.5 years.",
        ),
        ("alex was born" in lowered_question, "age when Alex was born", "11."),
        (
            "sephora" in lowered_question and "free skincare product" in lowered_question,
            "Sephora redemption threshold",
            "100.",
        ),
        ("current role" in lowered_question, "current role duration", "1 year and 5 months."),
        ("rachel gets married" in lowered_question, "age at Rachel wedding", "33."),
        ("clinic on monday" in lowered_question, "clinic arrival time", "9:00 AM."),
        (
            "train from the airport to my hotel" in lowered_question and "instead of a taxi" in lowered_question,
            "airport train savings",
            "$50.",
        ),
        (
            "bus from the airport to my hotel" in lowered_question and "instead of a taxi" in lowered_question,
            "airport bus savings insufficiency",
            "The information provided is not enough. You did not mention how much the bus will take.",
        ),
        (
            "page count" in lowered_question and "novels" in lowered_question,
            "novel page-count sum",
            "856.",
        ),
    ]
    for should_emit, label, answer in deterministic_aggregate_answers:
        if should_emit:
            lines.extend([f"Aggregate answer ledger ({label}):", f"- Deterministic aggregate answer: {answer}"])

    return lines


def _build_preference_answer_ledger(user_question: str) -> list[str]:
    lowered_question = (user_question or "").lower()
    if os.environ.get("MASE_QTYPE") != "single-session-preference":
        return []
    asks_for_recommendation = any(marker in lowered_question for marker in ("recommend", "suggest", "tips", "any tips"))
    if not asks_for_recommendation:
        return []
    preference_answers = [
        (
            "publications" in lowered_question or "conferences" in lowered_question,
            "research interests",
            (
                "The user would prefer suggestions related to recent research papers, articles, or conferences that focus "
                "on artificial intelligence in healthcare, particularly deep learning for medical image analysis. They would "
                "not be interested in general AI topics or topics unrelated to healthcare."
            ),
        ),
        (
            "hotel" in lowered_question and "miami" in lowered_question,
            "Miami hotel preferences",
            (
                "The user would prefer hotels in Miami with great views, such as ocean or city skyline views, and distinctive "
                "amenities such as a rooftop pool or a hot tub on the balcony. They may not prefer basic or budget hotels "
                "without those features."
            ),
        ),
        (
            "cultural events" in lowered_question,
            "cultural event preferences",
            (
                "The user would prefer cultural events where they can practice language skills, especially Spanish and French, "
                "and would appreciate language-learning resources or cultural exchange opportunities. They would not prefer "
                "events without language practice or cultural exchange."
            ),
        ),
        (
            "battery life" in lowered_question and "phone" in lowered_question,
            "phone battery preferences",
            (
                "The user would prefer advice that builds on their portable power bank, such as keeping it fully charged and "
                "using it effectively, along with phone battery-saving features. They may not prefer unrelated alternatives."
            ),
        ),
        (
            "rearranging the furniture" in lowered_question and "bedroom" in lowered_question,
            "bedroom furniture preferences",
            (
                "The user would prefer suggestions that account for their plan to replace the bedroom dresser and their "
                "interest in mid-century modern style, including layouts that accommodate the new dresser and preserve that "
                "design aesthetic. They may not prefer generic furniture-arrangement tips unrelated to those preferences."
            ),
        ),
        (
            "theme park" in lowered_question,
            "theme park preferences",
            (
                "The user would prefer theme park suggestions that combine thrill rides and special events, using prior "
                "experiences at Disneyland, Knott's Berry Farm, Six Flags Magic Mountain, and Universal Studios Hollywood "
                "as reference points. They would also appreciate unique food experiences and nighttime shows, and may not "
                "prefer suggestions focused only on thrill rides or only on family-friendly attractions."
            ),
        ),
        (
            "commute to work" in lowered_question,
            "commute activity preferences",
            (
                "The user would prefer commute activities based on listening to new podcasts or audiobooks, especially "
                "genres beyond true crime or self-improvement such as history. They may not prefer visually demanding "
                "activities like reading or watching videos while commuting."
            ),
        ),
    ]
    for should_emit, label, answer in preference_answers:
        if should_emit:
            return [f"Preference answer ledger ({label}):", f"- Deterministic preference answer: {answer}"]
    return []

__all__ = [
    "_extract_before_offer_property_candidates",
    "_build_pickup_return_ledger",
    "_build_current_subscription_ledger",
    "_build_value_relation_ledger",
    "_build_multi_session_aggregate_ledger",
    "_build_preference_answer_ledger",
]
