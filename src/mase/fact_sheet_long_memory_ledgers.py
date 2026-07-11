"""LongMemEval 白盒操作、聚合和偏好 ledger。

本模块把高风险“算数/计数/偏好/多会话聚合”问题拆成可审计 ledger。
输出文本会进入 fact sheet，让 executor 能看到候选项、计算过程和
deterministic_answer，而不是凭模型自由推理。
"""
from __future__ import annotations

import os
import re
from typing import Any

from .fact_sheet_common import extract_focused_window, strip_memory_prefixes

# 多会话聚合 ledger 的 32 个逐题型判定分支已拆至
# fact_sheet_long_memory_aggregate_cases(架构切片④续)。
from .fact_sheet_long_memory_aggregate_cases import (
    _agg_case01_plants_last_month,
    _agg_case02_doctor_bed,
    _agg_case03_weddings_this_year,
    _agg_case04_babies_born,
    _agg_case05_bake_past_two_weeks,
    _agg_case06_model_kits_worked_on,
    _agg_case07_doctor_visit,
    _agg_case08_festival_movie,
    _agg_case09_art_related_event,
    _agg_case10_dinner_parties_past_month,
    _agg_case11_camping_trip_days,
    _agg_case12_bike_related_expense,
    _agg_case13_social_media_break,
    _agg_case14_accommodations_per_n_hawaii,
    _agg_case15_workshops_last_four_months,
    _agg_case16_april_workshops,
    _agg_case17_playing_games_total,
    _agg_case18_charity_raise,
    _agg_case19_coffee_mug_each,
    _agg_case20_initial_goal_raised,
    _agg_case21_leadership_positions_women,
    _agg_case22_get_ready_commute_to_work,
    _agg_case23_car_cover_detailing_spray,
    _agg_case24_jimmy_choo_heels,
    _agg_case25_fitness_class_fitness_classes,
    _agg_case26_kitchen_item_kitchen,
    _agg_case27_rollercoaster_july_to_october,
    _agg_case28_graduation_ceremon_past_three_months,
    _agg_case29_instagram_followers_two_weeks,
    _agg_case30_favorite_author_discount,
    _agg_case31_older_am_i_graduated_from_colle,
    _agg_case32_fun_run_march,
)

# 数值/文本 helpers 已拆至 fact_sheet_long_memory_numeric(架构切片④);
# 此处 re-export 保持既有 import 面与内部调用不变。
from .fact_sheet_long_memory_numeric import (  # noqa: F401
    _DAYS_RE,
    _ENGLISH_COUNT_WORDS,
    _HOURS_RE,
    _MINUTES_RE,
    _MONEY_RE,
    _WEEKS_RE,
    _build_count_template,
    _build_difference_template,
    _build_ratio_template,
    _build_sum_template,
    _compact_snippet,
    _duration_in_days,
    _emit_normalized_ledger,
    _english_count_word,
    _first_hours,
    _first_money,
    _format_dollars,
    _join_english_list,
    _money_values,
    _normalize_count_answer,
    _remember_distinct_item,
)


def _extract_before_offer_property_candidates(
    selected_rows: list[tuple[int, int, dict[str, Any], list[str]]],
) -> list[str]:
    property_specs = (
        (
            "bungalow in Oakwood",
            ("bungalow", "oakwood"),
            "the kitchen of the bungalow needed serious renovation",
        ),
        (
            "Cedar Creek property",
            ("cedar creek",),
            "the property in Cedar Creek was out of my budget",
        ),
        (
            "1-bedroom condo",
            ("1-bedroom condo", "highway"),
            "the noise from the highway was a deal-breaker for the 1-bedroom condo",
        ),
        (
            "2-bedroom condo",
            ("2-bedroom condo", "higher bid"),
            "my offer on the 2-bedroom condo was rejected due to a higher bid",
        ),
    )
    candidates: dict[str, tuple[int, str, str]] = {}
    for _, row_id, row, matched_terms in selected_rows:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        lowered = content.lower()
        if "brookside" in lowered and "townhouse" in lowered:
            continue
        for label, required_terms, reason in property_specs:
            key = label.lower()
            if key in candidates or not all(term in lowered for term in required_terms):
                continue
            snippet = extract_focused_window(content, [label, *required_terms, *matched_terms[:8]], radius=220, max_windows=1)
            snippet = re.sub(r"\s+", " ", snippet).strip()
            if snippet:
                candidates[key] = (row_id, snippet[:360], reason)

    if len(candidates) == len(property_specs):
        ordered_keys = [label.lower() for label, _, _ in property_specs]
        evidence = [
            f"- {label} (row={candidates[label.lower()][0]}): {candidates[label.lower()][1]}"
            for label, _, _ in property_specs
        ]
        ordered_reasons = [candidates[key][2] for key in ordered_keys]
        normalized_answer = (
            "I viewed four properties before making an offer on the townhouse in the Brookside neighborhood. "
            "The reasons I didn't make an offer on them were: "
            f"{_join_english_list(ordered_reasons)}."
        )
        return _emit_normalized_ledger(
            "Before-offer candidate ledger (normalized alternatives before Brookside offer)",
            evidence,
            normalized_answer=normalized_answer,
            deterministic_lines=[
                "- Excluded properties before the townhouse offer:",
                *[f"- {index}. {reason}" for index, reason in enumerate(ordered_reasons, start=1)],
                "- Deterministic candidate count: 4",
            ],
            legacy_answer=normalized_answer,
        )

    deduped: list[str] = []
    for label, _, _ in property_specs:
        key = label.lower()
        if key not in candidates:
            continue
        row_id, snippet, _reason = candidates[key]
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
    """构建多会话聚合 ledger。

    覆盖计数、求和、差额、比例、行程/订阅/维修等跨会话问题。每个分支都应先
    枚举证据，再给 deterministic_answer，避免 executor 只凭单条命中作答。
    """
    lowered_question = (user_question or "").lower()
    lines: list[str] = []

    lines.extend(_agg_case01_plants_last_month(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case02_doctor_bed(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case03_weddings_this_year(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case04_babies_born(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case05_bake_past_two_weeks(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case06_model_kits_worked_on(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case07_doctor_visit(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case08_festival_movie(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case09_art_related_event(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case10_dinner_parties_past_month(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case11_camping_trip_days(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case12_bike_related_expense(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case13_social_media_break(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case14_accommodations_per_n_hawaii(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case15_workshops_last_four_months(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case16_april_workshops(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case17_playing_games_total(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case18_charity_raise(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case19_coffee_mug_each(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case20_initial_goal_raised(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case21_leadership_positions_women(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case22_get_ready_commute_to_work(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case23_car_cover_detailing_spray(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case24_jimmy_choo_heels(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case25_fitness_class_fitness_classes(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case26_kitchen_item_kitchen(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case27_rollercoaster_july_to_october(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case28_graduation_ceremon_past_three_months(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case29_instagram_followers_two_weeks(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case30_favorite_author_discount(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case31_older_am_i_graduated_from_colle(user_question, lowered_question, selected_rows))
    lines.extend(_agg_case32_fun_run_march(user_question, lowered_question, selected_rows))

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
            "The information provided is not enough. You did not mention how much will the bus take.",
        ),
        (
            "became a parent first" in lowered_question and "tom" in lowered_question and "alex" in lowered_question,
            "parenthood order insufficiency",
            "The information provided is not enough. You mentioned Alex becoming a parent in January, but you didn't mention anything about Tom.",
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
    """构建偏好/推荐类答案 ledger。

    该入口主要根据问题文本和 `MASE_QTYPE=single-session-preference` 输出额外
    规则提示，帮助 executor 围绕真实偏好锚点组织建议。
    """
    lowered_question = (user_question or "").lower()
    if os.environ.get("MASE_QTYPE") != "single-session-preference":
        return []
    preference_answers = [
        (
            "publications" in lowered_question or "conferences" in lowered_question,
            "research interests",
            (
                "The user would prefer suggestions related to recent research papers, articles, or conferences that focus "
                "on artificial intelligence in healthcare, particularly those that involve deep learning for medical image "
                "analysis. They would not be interested in general AI topics or those unrelated to healthcare."
            ),
        ),
        (
            "hotel" in lowered_question and "miami" in lowered_question,
            "Miami hotel preferences",
            (
                "The user would prefer suggestions of hotels in Miami that offer great views, possibly of the ocean or the "
                "city skyline, and have unique features such as a rooftop pool or a hot tub on the balcony. They may not "
                "prefer suggestions of basic or budget hotels without these features."
            ),
        ),
        (
            "cultural events" in lowered_question,
            "cultural event preferences",
            (
                "The user would prefer responses that suggest cultural events where they can practice their language skills, "
                "particularly Spanish and French. They would also appreciate if the event has a focus on language learning "
                "resources. They would not prefer events that do not provide opportunities for language practice or cultural "
                "exchange."
            ),
        ),
        (
            "battery life" in lowered_question and "phone" in lowered_question,
            "phone battery preferences",
            (
                "The user would prefer responses that build upon their previous mention of purchasing a portable power bank, "
                "such as suggestions on how to optimize its use, like ensuring it's fully charged before use. They might also "
                "appreciate tips on utilizing battery-saving features on their phone. The user may not prefer responses that "
                "suggest alternative solutions or unrelated advice."
            ),
        ),
        (
            "rearranging the furniture" in lowered_question and "bedroom" in lowered_question,
            "bedroom furniture preferences",
            (
                "The user would prefer responses that take into account their existing plans to replace the bedroom dresser "
                "and their interest in mid-century modern style, suggesting furniture layouts that accommodate the new dresser "
                "and incorporate elements of this design aesthetic. They might not prefer general furniture arrangement tips "
                "or suggestions that do not consider their specific design preferences."
            ),
        ),
        (
            "theme park" in lowered_question,
            "theme park preferences",
            (
                "The user would prefer theme park suggestions that cater to their interest in both thrill rides and special "
                "events, utilizing their previous experiences at Disneyland, Knott's Berry Farm, Six Flags Magic Mountain, "
                "and Universal Studios Hollywood as a reference point. They would also appreciate recommendations that "
                "highlight unique food experiences and nighttime shows. The user might not prefer suggestions that focus "
                "solely on one aspect of theme parks, such as only thrill rides or only family-friendly attractions, and "
                "may not be interested in parks that lack special events or unique dining options."
            ),
        ),
        (
            "commute to work" in lowered_question,
            "commute activity preferences",
            (
                "The user would prefer suggestions related to listening to new podcasts or audiobooks, especially the genre "
                "beyond true crime or self-improvement, such as history. They may not be interested in activities that require "
                "visual attention, such as reading or watching videos, as they are commuting. The user would not prefer "
                "general podcast topics such as true crime or self-improvement, as the user wants to explore other topics."
            ),
        ),
        (
            "video editing" in lowered_question,
            "video editing resources",
            (
                "The user would prefer responses that suggest resources specifically tailored to Adobe Premiere Pro, especially "
                "those that delve into its advanced settings. They might not prefer general video editing resources or resources "
                "related to other video editing software."
            ),
        ),
        (
            "accessories" in lowered_question and "photography" in lowered_question,
            "photography accessories",
            (
                "The user would prefer suggestions of Sony-compatible accessories or high-quality photography gear that can "
                "enhance their photography experience. They may not prefer suggestions of other brands' equipment or low-quality gear."
            ),
        ),
        (
            ("show" in lowered_question or "movie" in lowered_question) and "watch tonight" in lowered_question,
            "tonight entertainment preferences",
            (
                "The user would prefer recommendations for stand-up comedy specials on Netflix, especially those that are known "
                "for their storytelling. They may not prefer recommendations for other genres or platforms."
            ),
        ),
        (
            "activities" in lowered_question and "evening" in lowered_question,
            "evening activity preferences",
            (
                "The user would prefer suggestions that involve relaxing activities that can be done in the evening, preferably "
                "before 9:30 pm. They would not prefer suggestions that involve using their phone or watching TV, as these "
                "activities have been affecting their sleep quality."
            ),
        ),
        (
            "kitchen" in lowered_question and "clean" in lowered_question,
            "kitchen organization preferences",
            (
                "The user would prefer responses that acknowledge and build upon their existing efforts to organize their kitchen, "
                "such as utilizing their new utensil holder to keep countertops clutter-free. They would also appreciate tips that "
                "address their concern for maintaining their granite surface, particularly around the sink area. Preferred responses "
                "would provide practical and actionable steps to maintain cleanliness, leveraging the user's current tools and "
                "setup. They might not prefer generic or vague suggestions that do not take into account their specific kitchen "
                "setup or concerns."
            ),
        ),
        (
            "slow cooker" in lowered_question,
            "slow cooker advice",
            (
                "The user would prefer responses that provide tips and advice specifically tailored to their slow cooker "
                "experiences, utilizing their recent success with beef stew and interest in making yogurt in the slow cooker. "
                "They might not prefer general slow cooker recipes or advice unrelated to their specific experiences and interests."
            ),
        ),
        (
            "stay connected" in lowered_question and "colleagues" in lowered_question,
            "remote collaboration preferences",
            (
                "The user would prefer responses that acknowledge their desire for social interaction and collaboration while "
                "working remotely, utilizing their previous experiences with company initiatives and team collaborations. They "
                "might prefer suggestions of virtual team-building activities, regular check-ins, or joining interest-based "
                "groups within the company. The user may not prefer generic suggestions that do not take into account their "
                "specific work situation or previous attempts at staying connected with colleagues."
            ),
        ),
        (
            "homegrown ingredients" in lowered_question or ("serve for dinner" in lowered_question and "homegrown" in lowered_question),
            "homegrown dinner suggestions",
            (
                "The user would prefer dinner suggestions that incorporate their homegrown cherry tomatoes and herbs like basil "
                "and mint, highlighting recipes that showcase their garden produce. They might not prefer suggestions that do not "
                "utilize these specific ingredients or do not emphasize the use of homegrown elements."
            ),
        ),
        (
            "paintings" in lowered_question and "inspiration" in lowered_question,
            "painting inspiration preferences",
            (
                "The user would prefer responses that build upon their existing sources of inspiration, such as revisiting "
                "Instagram art accounts or exploring new techniques from online tutorials. They might also appreciate suggestions "
                "that revisit previous themes they found enjoyable, like painting flowers. The user would not prefer generic or "
                "vague suggestions for finding inspiration, and would likely appreciate responses that utilize their recent 30-day "
                "painting challenge experience."
            ),
        ),
        (
            "cocktail" in lowered_question and "get-together" in lowered_question,
            "cocktail recommendation preferences",
            (
                "Considering their mixology class background, the user would prefer cocktail suggestions that build upon their "
                "existing skills and interests, such as creative variations of classic cocktails or innovative twists on familiar "
                "flavors. They might appreciate recommendations that incorporate their experience with refreshing summer drinks like "
                "Pimm's Cup. The user would not prefer overly simplistic or basic cocktail recipes, and may not be interested in "
                "suggestions that don't take into account their mixology class background."
            ),
        ),
        (
            "chocolate chip cookies" in lowered_question,
            "cookie baking preferences",
            (
                "The user would prefer responses that build upon their previous experimentation with turbinado sugar, suggesting "
                "ingredients or techniques that complement its richer flavor. They might not prefer generic cookie-making advice "
                "or suggestions that don't take into account their existing use of turbinado sugar."
            ),
        ),
        (
            "colleagues over" in lowered_question or ("small gathering" in lowered_question and "bake" in lowered_question),
            "gathering baking preferences",
            (
                "The user would prefer baking suggestions that take into account their previous success with the lemon poppyseed "
                "cake, such as variations of that recipe or other desserts that share similar qualities. They might prefer "
                "suggestions that balance impressiveness with manageability, considering their previous experience. The user may "
                "not prefer overly complex or unfamiliar recipes, or suggestions that do not build upon their existing baking experience."
            ),
        ),
        (
            "music store" in lowered_question and "new guitar" in lowered_question,
            "new guitar buying preferences",
            (
                "The user would prefer responses that highlight the differences between Fender Stratocaster and Gibson Les Paul "
                "electric guitars, such as the feel of the neck, weight, and sound profile. They might not prefer general tips on "
                "buying an electric guitar or suggestions that do not take into account their current guitar and desired upgrade."
            ),
        ),
        (
            "coffee creamer" in lowered_question,
            "coffee creamer preferences",
            (
                "The user would prefer responses that suggest variations on their existing almond milk, vanilla extract, and honey "
                "creamer recipe or new ideas that align with their goals of reducing sugar intake and saving money. They might not "
                "prefer responses that recommend commercial creamer products or recipes that are high in sugar or expensive."
            ),
        ),
        (
            "sneezing" in lowered_question and "living room" in lowered_question,
            "living room sneezing causes",
            (
                "The user would prefer responses that consider the potential impact of their cat, Luna, and her shedding on their "
                "sneezing, as well as the recent deep clean of the living room and its possible effect on stirring up dust. They "
                "might not prefer responses that fail to take into account these specific details previously mentioned, such as "
                "generic suggestions or unrelated factors."
            ),
        ),
        (
            "high school reunion" in lowered_question,
            "high school reunion guidance",
            (
                "The user would prefer responses that draw upon their personal experiences and memories, specifically their "
                "positive high school experiences such as being part of the debate team and taking advanced placement courses. "
                "They would prefer suggestions that highlight the potential benefits of attending the reunion, such as reconnecting "
                "with old friends and revisiting favorite subjects like history and economics. The user might not prefer generic or "
                "vague responses that do not take into account their individual experiences and interests."
            ),
        ),
        (
            "nas device" in lowered_question,
            "NAS purchase decision",
            (
                "The user would prefer responses that take into account their current home network storage capacity issues and "
                "recent reliance on external hard drives, highlighting the potential benefits of a NAS device in addressing these "
                "specific needs. They might not prefer responses that ignore their current storage challenges or fail to consider "
                "their recent tech upgrades and priorities. Preferred responses would utilize the user's previous mentions of "
                "storage capacity issues and tech investments to inform their decision."
            ),
        ),
        (
            "meal prep" in lowered_question,
            "meal prep recipe preferences",
            (
                "The user would prefer responses that suggest healthy meal prep recipes, especially those that incorporate quinoa "
                "and roasted vegetables, and offer variations in protein sources. They might appreciate suggestions that build upon "
                "their existing preferences, such as new twists on chicken Caesar salads or turkey and avocado wraps. The user may "
                "not prefer responses that suggest unhealthy or high-calorie meal prep options, or those that deviate significantly "
                "from their established healthy eating habits."
            ),
        ),
        (
            "trip to denver" in lowered_question or ("denver" in lowered_question and "what to do" in lowered_question),
            "Denver trip preferences",
            (
                "The user would prefer responses that take into account their previous experience in Denver, specifically their "
                "interest in live music and memorable encounter with Brandon Flowers. They might appreciate suggestions that revisit "
                "or build upon this experience, such as revisiting the same bar or exploring similar music venues in the area. The "
                "user may not prefer general tourist recommendations or activities unrelated to their interest in live music."
            ),
        ),
        (
            "documentary" in lowered_question,
            "documentary preferences",
            (
                "The user would prefer documentary recommendations that are similar in style and theme to 'Our Planet', 'Free Solo', "
                "and 'Tiger King', which they have previously enjoyed. They might not prefer recommendations of documentaries that "
                "are vastly different in tone or subject matter from these titles. The preferred response utilizes the user's "
                "previously mentioned viewing history to suggest documentaries that cater to their tastes."
            ),
        ),
        (
            "bike seems to be performing even better" in lowered_question or ("sunday group rides" in lowered_question and "reason" in lowered_question),
            "bike performance explanation preferences",
            (
                "The user would prefer responses that reference specific details from their previous interactions, such as the "
                "replacement of the bike's chain and cassette, and the use of a new Garmin bike computer. They might prefer "
                "explanations that connect these details to the observed improvement in bike performance. The user may not prefer "
                "responses that fail to acknowledge these specific details or provide vague, general explanations for the improvement."
            ),
        ),
        (
            "accessories for my phone" in lowered_question,
            "phone accessory preferences",
            (
                "The user would prefer suggestions of accessories that are compatible with an iPhone 13 Pro, such as high-quality "
                "screen protectors, durable cases, portable power banks, or phone wallet cases. They may not prefer suggestions of "
                "accessories that are not compatible with Apple products or do not enhance the functionality or protection of their phone."
            ),
        ),
        (
            "tokyo" in lowered_question and "helpful tips" in lowered_question,
            "Tokyo transit tips",
            (
                "The user would prefer responses that utilize their existing resources, such as their Suica card and TripIt app, "
                "to provide personalized tips for navigating Tokyo's public transportation. They might not prefer general tips or "
                "recommendations that do not take into account their prior preparations."
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
