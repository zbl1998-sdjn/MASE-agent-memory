from __future__ import annotations

import json
import os
from pathlib import Path

FAILURE_PACK = Path(__file__).resolve().parent / "data" / "failure_clusters" / "longmemeval.json"


def test_longmemeval_failure_pack_is_seeded() -> None:
    payload = json.loads(FAILURE_PACK.read_text(encoding="utf-8"))
    assert payload["cases"]
    assert payload["cases"][0]["failure_mode"] == "multi_session_aggregation"

from benchmarks.runner import BenchmarkRunner
from benchmarks.schemas import BenchmarkSample
from event_bus import build_event_bus_snapshot, build_events_from_fact_card, query_event_bus
from executor import ExecutorAgent
from mase import get_system
from mase_tools.legacy import (
    _build_duration_ledger_rows,
    _build_english_search_profile,
    _build_money_ledger_rows,
    _duration_line_matches_question_focus,
    _expand_temporal_candidate_search_queries,
    _extract_between_event_days_from_results,
    _extract_current_count_reasoning_from_results,
    _extract_duration_by_event,
    _extract_elapsed_time_reasoning_from_results,
    _extract_english_countable_items,
    _extract_english_quantity_difference,
    _extract_event_order_reasoning,
    _extract_event_order_reasoning_from_results,
    _extract_multi_item_duration_total_reasoning_from_results,
    _extract_relevant_snippets,
    _extract_scalar_reasoning_notes,
    _extract_state_transition_count_reasoning,
    _extract_temporal_candidate_phrases,
    _match_event_candidate_line,
    _split_sentences,
    assess_evidence_chain,
    assess_question_contracts,
    extract_question_scope_filters,
    format_fact_sheet,
    plan_temporal_date_hints,
)
from memory_reflection import build_fact_card, resolve_coreferences_text
from orchestrator import _merge_scope_filters
from orchestrator import _slot_contract_state as orchestrator_slot_contract_state
from planner import _extract_temporal_candidate_phrases as planner_extract_temporal_candidate_phrases
from planner import build_planner_decision
from router import RouterAgent, _extract_keywords_from_question, _should_force_search_memory, filter_keywords


def build_executor() -> ExecutorAgent:
    return ExecutorAgent(model_interface=None)  # type: ignore[arg-type]


class StubExecutorModelInterface:
    def get_agent_config(self, _agent_name: str) -> dict[str, object]:
        return {}

    def describe_agent(self, _agent_name: str, *, mode: str = "") -> dict[str, object]:
        return {"mode": mode}

    def chat(self, *_args, **_kwargs):
        raise AssertionError("executor should have resolved deterministically before model call")


class StubRouterModel:
    fallbacks = {"router_parse_failed_action": "direct_answer"}

    def chat(self, *_args, **_kwargs):
        raise AssertionError("heuristic route should have short-circuited before model call")


def main() -> None:
    executor = build_executor()
    deterministic_executor = ExecutorAgent(model_interface=StubExecutorModelInterface())  # type: ignore[arg-type]

    doctors_fact_sheet = """
Aggregation worksheet:
- Countable items:
- 1. primary care physician
- 2. ENT specialist
- 3. dermatologist
- Deterministic count: 3 items
"""
    doctors_answer = executor._format_english_count_answer(
        "How many different doctors did I visit?",
        "3",
        doctors_fact_sheet,
    )
    assert "three different doctors" in doctors_answer.lower()
    assert "ent specialist" in doctors_answer.lower()

    bedtime_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I didn't get to bed until 2 AM last Wednesday.
"""
    bedtime_answer = executor._extract_deterministic_aggregation_answer(
        "What time did I go to bed the day before my doctor's appointment?",
        bedtime_fact_sheet,
    )
    assert bedtime_answer == "2 AM"

    wedding_fact_sheet = """
Aggregation worksheet:
- Atomic fact: My cousin Rachel's wedding at a vineyard in August was stunning.
- Atomic fact: My friend Emily finally got to tie the knot with her partner Sarah.
- Atomic fact: The bride, Jen, looked stunning in her bohemian-inspired dress, and her husband, Tom, was clearly smitten with her.
- Auxiliary atomic facts:
- Rachel and Mike had an amazing beach trip.
- Countable items:
- 1. Rachel's wedding
- 2. Emily and Sarah
- 3. Jen and Tom
- Deterministic count: 3 items
"""
    wedding_answer = executor._format_english_count_answer(
        "How many weddings have I attended in this year?",
        "3",
        wedding_fact_sheet,
    )
    assert "rachel and mike" in wedding_answer.lower()
    assert "emily and sarah" in wedding_answer.lower()
    assert "jen and tom" in wedding_answer.lower()

    property_fact_sheet = """
Aggregation worksheet:
- Atomic fact: The property in Cedar Creek was out of my league and did not fit my budget.
- Atomic fact: The noise from the highway was a deal-breaker for the 1-bedroom condo.
- Atomic fact: The 2-bedroom condo had a higher bid already.
- Atomic fact: The bungalow kitchen needed serious renovation.
- Countable items:
- 1. cedar creek property
- 2. 1-bedroom condo
- 3. 2-bedroom condo
- 4. bungalow
- Deterministic count: 4 items
"""
    property_answer = executor._build_brookside_property_answer(property_fact_sheet)
    assert "cedar creek was out of my budget" in property_answer.lower()
    assert "kitchen of the bungalow needed serious renovation" in property_answer.lower()

    platform_fact_sheet = """
Event cards:
- {"event_type": "social_followers", "display_name": "Instagram", "normalized_name": "instagram", "attributes": {"delta_followers": 120}}
- {"event_type": "social_followers", "display_name": "TikTok", "normalized_name": "tiktok", "attributes": {"delta_followers": 200}}
"""
    platform_answer = executor._extract_event_card_answer(
        "Which platform had the biggest followers increase?",
        platform_fact_sheet,
    )
    assert platform_answer == "TikTok"

    bake_fact_sheet = """
Aggregation worksheet:
- Deterministic item count: 4
Event cards:
- {"event_type": "bake", "display_name": "banana bread", "normalized_name": "banana bread", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "cookies", "normalized_name": "cookies", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "pie", "normalized_name": "pie", "attributes": {"count": 1}}
"""
    bake_answer = executor._extract_event_card_answer(
        "How many times did I bake in the last two weeks?",
        bake_fact_sheet,
    )
    assert bake_answer == "4"

    furniture_fact_sheet = """
    Event cards:
    - {"event_type": "furniture", "display_name": "couch", "normalized_name": "couch", "provenance": "event_card", "attributes": {"count": 1}}
    - {"event_type": "furniture", "display_name": "coffee table", "normalized_name": "coffee table", "provenance": "event_card", "attributes": {"count": 1}}
    - {"event_type": "furniture", "display_name": "mattress", "normalized_name": "mattress", "provenance": "event_card", "attributes": {"count": 1}}
    - {"event_type": "furniture", "display_name": "bookshelf", "normalized_name": "bookshelf", "provenance": "event_card", "attributes": {"count": 1}}
    - {"event_type": "furniture", "display_name": "West", "normalized_name": "west", "provenance": "event_segment", "attributes": {"count": 1}}
    - {"event_type": "furniture", "display_name": "Casper", "normalized_name": "casper", "provenance": "event_segment", "attributes": {"count": 1}}
    """
    furniture_answer = executor._extract_event_card_answer(
        "How many pieces of furniture did I buy, assemble, sell, or fix in the past few months?",
        furniture_fact_sheet,
    )
    assert furniture_answer == "4"

    frequency_answer = executor._enforce_english_answer_shape(
        "How many times did I bake something in the past two weeks?",
        "4 times",
        "Aggregation worksheet:\n",
    )
    assert frequency_answer == "4"

    coref_question = "How many weddings have I attended in this year?"
    resolved_coref_question = resolve_coreferences_text(coref_question, ["many", "weddings", "attended", "year"])
    assert "How year" not in resolved_coref_question
    assert "this year" in resolved_coref_question.lower()

    festival_fact_sheet = """
Aggregation worksheet:
- Countable items:
- 1. Portland Film Festival
- 2. Austin Film Festival
- 3. Seattle International Film Festival
- 4. AFI Fest
- Deterministic count: 4 items
"""
    festival_answer = executor._format_english_count_answer(
        "How many movie festivals have I attended?",
        "4",
        festival_fact_sheet,
    )
    assert festival_answer == "I attended four movie festivals."

    delta_complete_fact_sheet = """
Aggregation worksheet:
- Deterministic scalar value: 350 - 250 = 100 followers
- Intermediate verification: followers_start=250, followers_end=350, followers_delta=100
"""
    delta_complete = orchestrator_slot_contract_state(
        "How much did my followers increase in two weeks?",
        [],
        delta_complete_fact_sheet,
    )
    assert delta_complete["incomplete"] is False

    delta_incomplete_fact_sheet = """
Aggregation worksheet:
- Deterministic scalar value: 100 followers
"""
    delta_incomplete = orchestrator_slot_contract_state(
        "How much did my followers increase in two weeks?",
        [],
        delta_incomplete_fact_sheet,
    )
    assert delta_incomplete["incomplete"] is True
    assert "before" in " ".join(delta_incomplete["queries"]).lower()

    remaining_complete_fact_sheet = """
Aggregation worksheet:
- Deterministic scalar remaining: 300 - 190 = 110 pages
- Intermediate verification: total=300, current=190, remaining=110
"""
    remaining_complete = orchestrator_slot_contract_state(
        "How many pages do I have left to read?",
        [],
        remaining_complete_fact_sheet,
    )
    assert remaining_complete["incomplete"] is False

    remaining_incomplete_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I am currently on page 190.
"""
    remaining_incomplete = orchestrator_slot_contract_state(
        "How many pages do I have left to read?",
        [],
        remaining_incomplete_fact_sheet,
    )
    assert remaining_incomplete["incomplete"] is True
    assert "goal total" in " ".join(remaining_incomplete["queries"]).lower()

    non_remaining_fact_sheet = """
Aggregation worksheet:
- Countable items:
- 1. boots
- 2. new pair
- 3. blazer
- Deterministic count: 3 items
"""
    non_remaining_state = orchestrator_slot_contract_state(
        "How many items of clothing do I need to pick up or return from a store?",
        [],
        non_remaining_fact_sheet,
    )
    assert non_remaining_state["incomplete"] is False
    assert non_remaining_state["contract_type"] == ""

    percentage_complete_fact_sheet = """
Aggregation worksheet:
- Deterministic percentage: 2 / 5 = 40%
- Intermediate verification: part=2, whole=5
"""
    percentage_complete = orchestrator_slot_contract_state(
        "What percentage of the shoes I packed did I wear?",
        [],
        percentage_complete_fact_sheet,
    )
    assert percentage_complete["incomplete"] is False

    percentage_incomplete_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I packed five pairs of shoes.
"""
    percentage_incomplete = orchestrator_slot_contract_state(
        "What percentage of the shoes I packed did I wear?",
        [],
        percentage_incomplete_fact_sheet,
    )
    assert percentage_incomplete["incomplete"] is True
    assert "percentage" in " ".join(percentage_incomplete["queries"]).lower()

    unsupported_fact_sheet = """
Aggregation worksheet:
- Deterministic scalar value: 100 followers
"""
    unsupported_state = executor._slot_contract_state(
        "How much did my followers increase in two weeks?",
        unsupported_fact_sheet,
    )
    assert unsupported_state["incomplete"] is True

    money_fact_sheet = """
Aggregation worksheet:
- money_ledger={"amount": 120.0, "currency": "USD", "purpose": "charity", "source": "I donated $120 to the school charity drive.", "verb": "donated"}
- money_ledger={"amount": 80.0, "currency": "USD", "purpose": "charity", "source": "I donated $80 at the weekend fundraiser.", "verb": "donated"}
- contract_type=money_total_by_purpose
"""
    money_answer = executor._extract_deterministic_aggregation_answer(
        "How much money did I donate to charity in total?",
        money_fact_sheet,
    )
    assert money_answer == "$200"

    days_fact_sheet = """
Aggregation worksheet:
- event_ledger={"count": null, "days": 12.0, "event_type": "faith_activity", "location": [], "month": ["december"], "source": "I spent 12 days in December attending church services and Bible study."}
- event_ledger={"count": null, "days": 9.0, "event_type": "faith_activity", "location": [], "month": ["december"], "source": "I volunteered for 9 days at the December food drive."}
- contract_type=days_spent_by_scope
"""
    days_answer = executor._extract_deterministic_aggregation_answer(
        "How many days did I spend on faith activities in December?",
        days_fact_sheet,
    )
    assert days_answer == "21 days"

    broad_scope_days_fact_sheet = """
Aggregation worksheet:
- event_ledger={"count": null, "days": 5.0, "event_type": "travel", "location": ["yellowstone national park"], "month": [], "source": "I just got back from an amazing 5-day camping trip to Yellowstone National Park last month."}
- event_ledger={"count": null, "days": 3.0, "event_type": "travel", "location": ["big sur"], "month": ["april"], "source": "I just got back from a 3-day solo camping trip to Big Sur in early April."}
"""
    broad_scope_days_state = orchestrator_slot_contract_state(
        "How many days did I spend on camping trips in the United States this year?",
        [],
        broad_scope_days_fact_sheet,
    )
    assert broad_scope_days_state["incomplete"] is False
    assert broad_scope_days_state["contract_type"] == "days_spent_by_scope"
    broad_scope_days_assessment = assess_evidence_chain(
        "How many days did I spend on camping trips in the United States this year?",
        [
            {
                "summary": "I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
                "user_query": "",
                "assistant_response": "",
            },
            {
                "summary": "I just got back from a 3-day solo camping trip to Big Sur in early April.",
                "user_query": "",
                "assistant_response": "",
            },
        ],
    )
    assert broad_scope_days_assessment["verifier_action"] != "refuse"
    assert "relation_mismatch" not in broad_scope_days_assessment["reason_codes"]
    camping_duration_rows = _build_duration_ledger_rows(
        "How many days did I spend on camping trips in the United States this year?",
        [
            {
                "summary": "I just got back from a 7-day family road trip to Utah.",
                "user_query": "",
                "assistant_response": "",
            },
            {
                "summary": "I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
                "user_query": "",
                "assistant_response": "",
            },
        ],
    )
    assert len(camping_duration_rows) == 1
    assert camping_duration_rows[0]["days"] == 5.0
    assert _duration_line_matches_question_focus(
        "How many days did I spend on camping trips in the United States this year?",
        "I just got back from a 7-day family road trip to Utah.",
    ) is False
    assert _duration_line_matches_question_focus(
        "How many days did I spend on camping trips in the United States this year?",
        "I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
    ) is True

    duration_fact_sheet = """
Aggregation worksheet:
- Deterministic sum: 2 weeks + 1.5 weeks = 3.5 weeks
- deterministic_answer=2 weeks + 1.5 weeks = 3.5 weeks
"""
    duration_state = orchestrator_slot_contract_state(
        "How many weeks did it take me to watch all the Marvel Cinematic Universe and Star Wars movies?",
        [],
        duration_fact_sheet,
    )
    assert duration_state["incomplete"] is False
    assert duration_state["contract_type"] == "duration_total"

    mixed_events_fact_sheet = """
Aggregation worksheet:
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["april"], "source": "I attended an April workshop on design systems."}
- event_ledger={"count": null, "days": null, "event_type": "lecture", "location": [], "month": ["april"], "source": "I went to an April lecture on accessibility."}
- event_ledger={"count": null, "days": null, "event_type": "conference", "location": [], "month": ["april"], "source": "I joined an April conference on front-end tooling."}
- contract_type=event_total_mixed_types
"""
    mixed_events_answer = executor._extract_deterministic_aggregation_answer(
        "How many workshops, lectures, and conferences did I attend in April?",
        mixed_events_fact_sheet,
    )
    assert mixed_events_answer == "3"

    state_fact_sheet = """
Aggregation worksheet:
- state_ledger={"effective_date": ["january"], "entity": "Wired", "source": "I am currently subscribed to Wired magazine.", "state": "active"}
- state_ledger={"effective_date": ["february"], "entity": "The Atlantic", "source": "I am currently subscribed to The Atlantic.", "state": "active"}
- state_ledger={"effective_date": ["march"], "entity": "National Geographic", "source": "I cancelled my National Geographic subscription.", "state": "cancelled"}
- contract_type=current_state_count
"""
    state_answer = executor._extract_deterministic_aggregation_answer(
        "How many magazine subscriptions do I currently have?",
        state_fact_sheet,
    )
    assert state_answer == "2"

    timeline_fact_sheet = """
Aggregation worksheet:
- education_ledger={"completion_year": 2014, "duration_years": 4.0, "source": "I spent 4 years in high school and graduated in 2014.", "stage": "high_school"}
- education_ledger={"completion_year": 2018, "duration_years": 4.0, "source": "My bachelor degree took 4 years and I finished in 2018.", "stage": "bachelor"}
- contract_type=timeline_composition
"""
    timeline_answer = executor._extract_deterministic_aggregation_answer(
        "How many years of formal education did I complete from high school through my bachelor degree?",
        timeline_fact_sheet,
    )
    assert timeline_answer == "8 years"

    frequency_fact_sheet = """
Aggregation worksheet:
- event_ledger={"count": 3.0, "days": null, "event_type": "rollercoaster", "location": [], "month": [], "source": "At the park I rode three rollercoasters."}
- event_ledger={"count": 2.0, "days": null, "event_type": "rollercoaster", "location": [], "month": [], "source": "On the second visit I rode two rollercoasters."}
- contract_type=multi_item_frequency
"""
    frequency_answer = executor._extract_deterministic_aggregation_answer(
        "How many times did I ride rollercoasters?",
        frequency_fact_sheet,
    )
    assert frequency_answer == "5 times"
    frequency_shaped = executor._enforce_english_answer_shape(
        "How many times did I ride rollercoasters?",
        "5",
        frequency_fact_sheet,
    )
    assert frequency_shaped == "5 times"

    duration_total_fact_sheet = """
    - I watched all 22 Marvel Cinematic Universe movies in two weeks.
    - I finished the main Star Wars films in a week and a half.
    """
    duration_total_answer = executor._extract_direct_duration_answer(
        "How many weeks did it take me to watch all the Marvel Cinematic Universe movies and the main Star Wars films?",
        duration_total_fact_sheet,
    )
    assert duration_total_answer == "3.5 weeks"

    driving_total_fact_sheet = """
    - I drove for four hours to Outer Banks in North Carolina.
    - I drove for five hours to the mountains in Tennessee.
    - I drove for six hours to Washington D.C.
    """
    driving_total_answer = executor._extract_direct_duration_answer(
        "How many hours in total did I spend driving to my three road trip destinations combined?",
        driving_total_fact_sheet,
    )
    assert driving_total_answer == "15 hours"

    games_total_fact_sheet = """
    - I spent around 70 hours playing Assassin's Creed Odyssey.
    - Hyper Light Drifter took me 5 hours to finish.
    - The Last of Us Part II took me 30 hours to finish.
    - Celeste took me 10 hours to complete.
    - The Last of Us Part II on normal difficulty took me 25 hours to complete.
    """
    games_total_answer = executor._extract_direct_duration_answer(
        "How many hours have I spent playing games in total?",
        games_total_fact_sheet,
    )
    assert games_total_answer == "140 hours"

    handbag_answer = executor._extract_direct_money_answer(
        "How much did I spend on a designer handbag?",
        """
        - I remember buying a designer handbag for a pretty penny - $800, to be exact.
        - I also spent $50 on a generic luxury accessory.
        """,
    )
    assert handbag_answer == "$800"

    shirts_answer = executor._extract_direct_count_answer(
        "How many shirts did I pack for my 5-day trip to Costa Rica?",
        """
        - I brought 7 shirts and 5 pairs of shorts, but I only ended up wearing 3 shirts.
        - I should pack 1-2 versatile shirts for a short trip.
        """,
    )
    assert shirts_answer == "7"

    apartment_answer = executor._extract_direct_duration_answer(
        "How long did it take to move to the new apartment?",
        """
        - It took me and my friends around 5 hours to move everything into the new apartment.
        - I spent 7 hours sorting boxes before the move.
        """,
    )
    assert apartment_answer == "5 hours"

    screen_time_fact_sheet = """
    [1] Time：2023-05-27 04-20-00
    Summary：I've been averaging around 2 hours of screen time on Instagram per day for the past two weeks, which is way too much.
    Relevant lines:
    - I've been averaging around 2 hours of screen time on Instagram per day for the past two weeks, which is way too much.
    """
    screen_time_answer = executor._enforce_english_answer_shape(
        "How much screen time have I been averaging on Instagram per day?",
        "8.57 minutes",
        screen_time_fact_sheet,
    )
    assert screen_time_answer == "2 hours"

    social_breaks_fact_sheet = """
    - I took a 10-day break from social media in mid-February.
    - I took a 7-day break from social media in mid-January.
    """
    social_breaks_answer = executor._extract_direct_duration_answer(
        "How many days did I take social media breaks in total?",
        social_breaks_fact_sheet,
    )
    assert social_breaks_answer == "17 days"

    frequency_only = executor._enforce_english_answer_shape(
        "How many times did I bake something in the past two weeks?",
        "4 times",
        "Aggregation worksheet:\n",
    )
    assert frequency_only == "4"

    plant_items = _extract_english_countable_items(
        "How many plants did I acquire in the last month?",
        [
            "I actually use a mixture of water and fertilizer when I water my plants, which I got from the nursery where I bought the peace lily and a succulent plant two weeks ago.",
            "I'm also wondering if I should repot my snake plant, which I got from my sister last month.",
            "Can you tell me more about the ideal soil conditions for basil plants?",
        ],
    )
    assert set(plant_items) == {"peace lily", "succulent", "snake plant"}
    assert "along" not in plant_items

    museum_items = _extract_english_countable_items(
        "How many different museums or galleries did I visit in December?",
        [
            "I visited the Museum of Modern Art (MoMA) in December.",
            "I went to the Metropolitan Museum of Art last winter.",
            "I'm looking for museum recommendations in December.",
        ],
    )
    assert len(museum_items) == 2
    assert any("moma" in item.lower() for item in museum_items)
    assert any("metropolitan museum" in item.lower() for item in museum_items)
    museum_visit_assessment = assess_evidence_chain(
        "How many different museums or galleries did I visit in February?",
        [
            {
                "summary": "I took my niece to the Natural History Museum on 2/8 and she loved the dinosaur exhibit!",
                "user_query": "",
                "assistant_response": "",
            },
            {
                "summary": "I visited the Museum of Modern Art in February.",
                "user_query": "",
                "assistant_response": "",
            },
        ],
    )
    assert museum_visit_assessment["verifier_action"] != "refuse"
    assert "museum_gallery_visit_missing" not in museum_visit_assessment["reason_codes"]

    assert _duration_line_matches_question_focus(
        "How many hours in total did I spend playing games?",
        "I finished The Last of Us Part II in 27 hours.",
    ) is True
    assert _duration_line_matches_question_focus(
        "How many hours in total did I spend playing games?",
        "I played Celeste for 5 hours.",
    ) is True
    assert executor._duration_row_supports_question(
        "How many hours have I spent playing games in total?",
        {"source": "I didn't know it took them 5-6 years to develop the game."},
    ) is False

    bake_contract_fact_sheet = """
- event_ledger={"count": 1, "days": null, "event_type": "bake", "source": "By the way, I made a delicious whole wheat baguette last Saturday"}
- event_ledger={"count": 1, "days": null, "event_type": "bake", "source": "By the way, I just baked a chocolate cake for my sister's birthday party last weekend"}
- event_ledger={"count": 1, "days": null, "event_type": "bake", "source": "By the way, I just used my oven's convection setting for the first time last Thursday to bake a batch of cookies"}
- event_ledger={"count": 1, "days": null, "event_type": "bake", "source": "I'm looking for some advice on improving my sourdough starter"}
"""
    bake_contract = assess_question_contracts(
        "How many times did I bake something in the past two weeks?",
        [],
        bake_contract_fact_sheet,
    )
    assert bake_contract["incomplete"] is False

    furniture_fact_sheet = """
    Event cards:
    - {"attributes": {"count": 1}, "event_type": "furniture", "normalized_name": "bookshelf", "provenance": "event_card", "source": "Oh, and speaking of organizing, I finally assembled that IKEA bookshelf for my home office about two months ago"}
    - {"attributes": {"count": 1}, "event_type": "furniture", "normalized_name": "coffee table", "provenance": "event_card", "source": "I just got a new coffee table and rearranged my living room"}
    - {"attributes": {"count": 1}, "event_type": "furniture", "normalized_name": "mattress", "provenance": "event_card", "source": "By the way, I've been meaning to get a new mattress for ages"}
    - {"attributes": {"count": 1}, "event_type": "furniture", "normalized_name": "couch", "provenance": "event_card", "source": "I'm thinking of getting some new throw pillows for my couch"}
    Aggregation worksheet:
    - Deterministic item count: 7
    """
    assert (
        executor._extract_direct_count_answer(
            "How many pieces of furniture did I buy, assemble, sell, or fix in the past few months?",
            furniture_fact_sheet,
        )
        == "4"
    )

    truncated_record = {
        "timestamp": "2026-04-13T19:44:44",
        "user_query": "I attended a digital marketing workshop on March 15-16, and I paid $500 to attend, and it was worth it!",
        "assistant_response": "",
        "semantic_summary": "I attended a digital marketing workshop on March 15-16",
        "memory_profile": {},
        "key_entities": [],
        "topic_tokens": [],
        "language": "en",
    }
    fact_card = build_fact_card(truncated_record, "memory.json")
    assert "$500" in fact_card["source_span"]

    contract_fail_assessment = assess_evidence_chain(
        "How much money did I donate to charity in total?",
        [],
        contract_state={
            "required": True,
            "complete": False,
            "incomplete": True,
            "reason": "money-purpose-gap",
            "contract_type": "money_total_by_purpose",
            "failure_bucket": "retrieval_gap",
            "missing_slots": ["amount", "purpose"],
            "queries": ["charity amount"],
        },
    )
    assert contract_fail_assessment["level"] == "low"
    assert contract_fail_assessment["verifier_action"] == "refuse"
    assert "contract_gate_fail" in contract_fail_assessment["reason_codes"]

    benchmark_case_dir = Path(
        "E:\\MASE-demo\\memory_runs\\benchmark-longmemeval_s-haystack-20260415-070241-885819\\e47becba"
    )
    previous_memory_dir = os.environ.get("MASE_MEMORY_DIR")
    try:
        os.environ["MASE_MEMORY_DIR"] = str(benchmark_case_dir)
        system = get_system(reload=True)
        trace = system.run_with_trace("What degree did I graduate with?", log=False)
        assert trace.answer == "Business Administration"
        assert trace.route.action == "search_memory"
        assert trace.evidence_assessment is not None
    finally:
        if previous_memory_dir is None:
            os.environ.pop("MASE_MEMORY_DIR", None)
        else:
            os.environ["MASE_MEMORY_DIR"] = previous_memory_dir

    class BaselineRetryRunner(BenchmarkRunner):
        def __init__(self) -> None:
            super().__init__(baseline_profile="ollama-qwen25-7b", sample_retry_count=2, sample_retry_delay_seconds=0)
            self.calls = 0

        def _run_sample_once(self, sample: BenchmarkSample, run_root: Path, attempt: int) -> dict[str, object]:
            self.calls += 1
            return {
                "id": sample.id,
                "benchmark": sample.benchmark,
                "case_memory_dir": str(run_root),
                "mase": {
                    "answer": "3",
                    "score": {"score": 1.0, "all_matched": True},
                    "error": None,
                    "error_kind": None,
                    "completed": True,
                },
                "baseline": {
                    "answer": "",
                    "score": {"score": 0.0, "all_matched": False},
                    "error": "502 Bad Gateway",
                    "error_kind": "infra_error",
                    "completed": False,
                },
            }

    retry_runner = BaselineRetryRunner()
    retry_result = retry_runner.run_sample(
        BenchmarkSample(
            id="retry-case",
            benchmark="longmemeval_s",
            task_type="long_memory",
            question="How many items did I buy?",
            ground_truth="3",
        ),
        Path("."),
    )
    assert retry_runner.calls == 1
    assert retry_result["attempt_count"] == 1

    direct_fail_question = "Which event happened first, my cousin's wedding or Michael's engagement party?"
    assert _should_force_search_memory(direct_fail_question) is True
    assert _extract_keywords_from_question(direct_fail_question) == ["__FULL_QUERY__"]
    assert filter_keywords([], direct_fail_question) == ["__FULL_QUERY__"]
    assert _extract_keywords_from_question("How often do I see my therapist, Dr. Smith?") == ["__FULL_QUERY__"]
    assert _extract_keywords_from_question("Where did Rachel move to after her recent relocation?") == ["__FULL_QUERY__"]
    assert _should_force_search_memory("How many videos of Corey Schafer's Python programming series have I completed so far?") is True
    assert _extract_keywords_from_question("How many videos of Corey Schafer's Python programming series have I completed so far?") == ["__FULL_QUERY__"]

    route_guard_question = "Do I have a spare screwdriver for opening up my laptop?"
    assert _should_force_search_memory(route_guard_question) is True
    router = RouterAgent(StubRouterModel())  # type: ignore[arg-type]
    routed = router.decide(route_guard_question)
    assert routed["action"] == "search_memory"
    assert routed["keywords"] == ["__FULL_QUERY__"]

    planner_decision = build_planner_decision(
        "How many items of clothing do I need to pick up or return from a store?",
        "search_memory",
        ["__FULL_QUERY__"],
        "grounded_answer",
        "reasoning",
        True,
        3,
    )
    assert "__FULL_QUERY__" not in planner_decision.query_variants
    assert "How many" not in planner_decision.query_variants

    temporal_planner_decision = build_planner_decision(
        "How many weeks ago did I buy the chandelier with my aunt?",
        "search_memory",
        ["__FULL_QUERY__"],
        "grounded_answer",
        "reasoning",
        True,
        3,
    )
    assert temporal_planner_decision.active_date_scan is True
    assert any("aunt" in item.lower() or "chandelier" in item.lower() for item in temporal_planner_decision.query_variants)
    consecutive_temporal_plan = build_planner_decision(
        "How many months have passed since I participated in two charity events in a row, on consecutive days?",
        "search_memory",
        ["__FULL_QUERY__"],
        "grounded_answer",
        "reasoning",
        True,
        3,
    )
    assert (consecutive_temporal_plan.memory_limit or 0) >= 8
    assert any("consecutive days" in item.lower() for item in consecutive_temporal_plan.query_variants)
    assert any(item.lower() == "charity events" for item in consecutive_temporal_plan.query_variants)
    expanded_temporal_queries = _expand_temporal_candidate_search_queries(
        "How many weeks ago did I meet up with my aunt and receive the crystal chandelier?"
    )
    assert any(item.lower() == "crystal chandelier" for item in expanded_temporal_queries)
    assert any(item.lower() == "my aunt" for item in expanded_temporal_queries)
    charity_temporal_queries = _expand_temporal_candidate_search_queries(
        "How many months have passed since I participated in two charity events in a row, on consecutive days?"
    )
    assert any(item.lower() == "charity events" for item in charity_temporal_queries)
    assert any("consecutive days" in item.lower() for item in charity_temporal_queries)
    generic_trip_planner_decision = build_planner_decision(
        "What is the order of the three trips I took in the past three months, from earliest to latest?",
        "search_memory",
        ["__FULL_QUERY__"],
        "grounded_answer",
        "reasoning",
        True,
        3,
    )
    assert any(item.lower() == "day hike" for item in generic_trip_planner_decision.query_variants)
    assert any(item.lower() == "camping trip" for item in generic_trip_planner_decision.query_variants)

    polluted_profile = _build_english_search_profile(
        ["__FULL_QUERY__"],
        full_query="How long is my daily commute to work?",
        query_variants=["__FULL_QUERY__", "How long", "full query", "day"],
    )
    assert "day" not in [item.lower() for item in polluted_profile["exact_phrases"]]
    assert "how" not in [item.lower() for item in polluted_profile["literal_terms"]]
    assert "full" not in [item.lower() for item in polluted_profile["literal_terms"]]
    assert "query" not in [item.lower() for item in polluted_profile["literal_terms"]]

    split_sentences = _split_sentences(
        "By the way, I recently attended the Sunday mass at St. Mary's Church on January 2nd. It was wonderful."
    )
    assert split_sentences[0].endswith("January 2nd")
    assert "St. Mary's Church" in split_sentences[0]

    between_days_notes = _extract_scalar_reasoning_notes(
        "How many days had passed between the Sunday mass and Ash Wednesday?",
        [
            "By the way, I recently attended the Sunday mass at St. Mary's Church on January 2nd.",
            "I also went to the Ash Wednesday service at the cathedral on February 1st.",
        ],
    )
    between_days_fact_sheet = "Aggregation worksheet:\n" + "\n".join(between_days_notes)
    between_days_answer = executor._extract_deterministic_aggregation_answer(
        "How many days had passed between the Sunday mass and Ash Wednesday?",
        between_days_fact_sheet,
    )
    assert between_days_answer == "30 days"

    between_days_result_notes = _extract_between_event_days_from_results(
        "How many days passed between my visit to the Museum of Modern Art (MoMA) and the Ancient Civilizations exhibit at the Metropolitan Museum of Art?",
        [
            {
                "user_query": "How many days passed between my visit to the Museum of Modern Art (MoMA) and the Ancient Civilizations exhibit at the Metropolitan Museum of Art?",
                "assistant_response": "",
                "summary": "How many days passed between my visit to the Museum of Modern Art (MoMA) and the Ancient Civilizations exhibit at the Metropolitan Museum of Art?",
                "timestamp": "2026-04-14T14:55:38",
                "metadata": {"source_timestamp": "2026-04-14T14:55:38"},
            },
            {
                "user_query": "I just got back from a guided tour at the Museum of Modern Art focused on 20th-century modern art movements.",
                "assistant_response": "",
                "summary": "Visited MoMA today.",
                "timestamp": "2023-01-08T12:49:00",
                "metadata": {"source_timestamp": "2023-01-08T12:49:00"},
            },
            {
                "user_query": "I've always been interested in ancient civilizations, which is why I attended the Ancient Civilizations exhibit at the Metropolitan Museum of Art today.",
                "assistant_response": "",
                "summary": "Visited the Ancient Civilizations exhibit at the Met.",
                "timestamp": "2023-01-15T00:27:00",
                "metadata": {"source_timestamp": "2023-01-15T00:27:00"},
            },
        ],
    )
    assert any("= 7 days" in note for note in between_days_result_notes)
    assert _extract_temporal_candidate_phrases(
        "How many days passed between my visit to the Museum of Modern Art (MoMA) and the 'Ancient Civilizations' exhibit at the Metropolitan Museum of Art?"
    ) == [
        "the Museum of Modern Art (MoMA)",
        "the 'Ancient Civilizations' exhibit at the Metropolitan Museum of Art",
    ]
    assert planner_extract_temporal_candidate_phrases(
        "How many days passed between my visit to the Museum of Modern Art (MoMA) and the 'Ancient Civilizations' exhibit at the Metropolitan Museum of Art?"
    ) == [
        "the Museum of Modern Art (MoMA)",
        "the 'Ancient Civilizations' exhibit at the Metropolitan Museum of Art",
    ]

    farmfresh_between_days_notes = _extract_between_event_days_from_results(
        "How many days passed between when I cancelled FarmFresh and when I did online grocery shopping from Instacart?",
        [
            {
                "user_query": "I cancelled my FarmFresh subscription today because I wasn't using it enough.",
                "assistant_response": "",
                "summary": "Cancelled FarmFresh subscription.",
                "timestamp": "2023-01-05T09:00:00",
                "metadata": {"source_timestamp": "2023-01-05T09:00:00"},
            },
            {
                "user_query": "I did online grocery shopping from Instacart today and stocked up on produce.",
                "assistant_response": "",
                "summary": "Ordered groceries from Instacart.",
                "timestamp": "2023-02-28T18:00:00",
                "metadata": {"source_timestamp": "2023-02-28T18:00:00"},
            },
        ],
    )
    assert any("= 54 days" in note for note in farmfresh_between_days_notes)

    herb_between_days_notes = _extract_between_event_days_from_results(
        "How many days passed between the day I started watering my herb garden and the day I harvested my first batch of fresh herbs?",
        [
            {
                "user_query": "How many days passed between the day I started watering my herb garden and the day I harvested my first batch of fresh herbs?",
                "assistant_response": "",
                "summary": "How many days passed between the day I started watering my herb garden and the day I harvested my first batch of fresh herbs?",
                "timestamp": "2026-04-14T15:04:52",
                "metadata": {"source_timestamp": "2026-04-14T15:04:52"},
            },
            {
                "user_query": "I started watering my herb garden kit today and checked the soil moisture before dinner.",
                "assistant_response": "",
                "summary": "Started watering the herb garden kit.",
                "timestamp": "2023-03-22T11:41:00",
                "metadata": {"source_timestamp": "2023-03-22T11:41:00"},
            },
            {
                "user_query": "I just harvested my first batch of fresh herbs from the herb garden kit today and I'm excited to cook with them.",
                "assistant_response": "",
                "summary": "Harvested the first batch of fresh herbs.",
                "timestamp": "2023-04-15T17:48:00",
                "metadata": {"source_timestamp": "2023-04-15T17:48:00"},
            },
        ],
    )
    assert any("= 24 days" in note for note in herb_between_days_notes)
    herb_fact_sheet = format_fact_sheet(
        [
            {
                "user_query": "I just harvested my first batch of fresh herbs from the herb garden kit today and I'm excited to cook with them.",
                "assistant_response": "",
                "summary": "Harvested the first batch of fresh herbs.",
                "timestamp": "2023-04-15T17:48:00",
                "date": "2023-04-15",
                "time": "17-48-00",
                "metadata": {"source_timestamp": "2023-04-15T17:48:00"},
            },
            {
                "user_query": "I'd like to know more about composting. I started creating a compost bin in my backyard using a wooden pallet and started layering green and brown materials.",
                "assistant_response": "",
                "summary": "Started a backyard compost bin.",
                "timestamp": "2023-04-15T17:48:00",
                "date": "2023-04-15",
                "time": "17-48-00",
                "metadata": {"source_timestamp": "2023-04-15T17:48:00"},
            },
            {
                "user_query": "Read the chapter 15 { CHAPTER FIFTEEN RULE #6 Crawl Before You Walk, Walk Before You Run }",
                "assistant_response": "",
                "summary": "Read a book chapter.",
                "timestamp": "2023-04-15T22:06:00",
                "date": "2023-04-15",
                "time": "22-06-00",
                "metadata": {"source_timestamp": "2023-04-15T22:06:00"},
            },
            {
                "user_query": "I'm looking for some advice on upgrading my brake pads.",
                "assistant_response": "",
                "summary": "Asked about brake pads.",
                "timestamp": "2023-04-15T20:29:00",
                "date": "2023-04-15",
                "time": "20-29-00",
                "metadata": {"source_timestamp": "2023-04-15T20:29:00"},
            },
            {
                "user_query": "monastery or courts were one resided, there were some generalities.",
                "assistant_response": "",
                "summary": "Historical reading notes.",
                "timestamp": "2023-03-19T17:59:00",
                "date": "2023-03-19",
                "time": "17-59-00",
                "metadata": {"source_timestamp": "2023-03-19T17:59:00"},
            },
            {
                "user_query": "I'm planning to make a salad for dinner tonight and I want to use some fresh herbs. Can you give me some advice on how to keep my herbs fresh for a longer period? By the way, I started watering my herb garden every morning today, and I'm excited to see them grow.",
                "assistant_response": "",
                "summary": "Started watering the herb garden kit.",
                "timestamp": "2023-03-22T11:41:00",
                "date": "2023-03-22",
                "time": "11-41-00",
                "metadata": {"source_timestamp": "2023-03-22T11:41:00"},
            },
        ],
        question="How many days passed between the day I started watering my herb garden and the day I harvested my first batch of fresh herbs?",
        max_items=5,
    )
    assert "Deterministic delta: 2023-03-22 to 2023-04-15 = 24 days" in herb_fact_sheet

    event_order_notes = _extract_event_order_reasoning(
        "Which event happened first, my cousin's wedding or Michael's engagement party?",
        [
            "My cousin's wedding was on June 14th at the vineyard.",
            "Michael's engagement party happened on April 9th at the rooftop bar.",
        ],
    )
    event_order_fact_sheet = "Aggregation worksheet:\n" + "\n".join(event_order_notes)
    event_order_answer = executor._extract_deterministic_aggregation_answer(
        "Which event happened first, my cousin's wedding or Michael's engagement party?",
        event_order_fact_sheet,
    )
    assert event_order_answer == "michael's engagement party"

    haystack_event_order_notes = _extract_event_order_reasoning_from_results(
        "Which event happened first, my cousin's wedding or Michael's engagement party?",
        [
            {
                "user_query": "My cousin's wedding was incredible at the vineyard.",
                "assistant_response": "",
                "summary": "Wedding update",
                "timestamp": "2023-06-14T20:00:00",
                "metadata": {
                    "session_id": "sharegpt_future_id",
                    "source_timestamp": "2023-06-14T20:00:00",
                },
            },
            {
                "user_query": "Michael's engagement party happened at the rooftop bar.",
                "assistant_response": "",
                "summary": "Engagement update",
                "timestamp": "2023-04-09T19:30:00",
                "metadata": {
                    "session_id": "sharegpt_past_id",
                    "source_timestamp": "2023-04-09T19:30:00",
                },
            },
        ],
    )
    assert any("deterministic event order: first = michael's engagement party" in note.lower() for note in haystack_event_order_notes)

    ordered_events_notes = _extract_event_order_reasoning_from_results(
        "What is the order of the three events: 'I signed up for the rewards program at ShopRite', 'I used a Buy One Get One Free coupon on Luvs diapers at Walmart', and 'I redeemed $12 cashback for a $10 Amazon gift card from Ibotta'?",
        [
            {
                "user_query": "What is the order of the three events: 'I signed up for the rewards program at ShopRite', 'I used a Buy One Get One Free coupon on Luvs diapers at Walmart', and 'I redeemed $12 cashback for a $10 Amazon gift card from Ibotta'?",
                "assistant_response": "",
                "summary": "What is the order of the three events: 'I signed up for the rewards program at ShopRite', 'I used a Buy One Get One Free coupon on Luvs diapers at Walmart', and 'I redeemed $12 cashback for a $10 Amazon gift card from Ibotta'?",
                "timestamp": "2026-04-14T15:11:04",
                "metadata": {"source_timestamp": "2026-04-14T15:11:04"},
            },
            {
                "user_query": "I used a Buy One Get One Free coupon on Luvs diapers at Walmart.",
                "assistant_response": "",
                "summary": "Used the Walmart diaper coupon.",
                "timestamp": "2023-04-01T10:00:00",
                "metadata": {"source_timestamp": "2023-04-01T10:00:00"},
            },
            {
                "user_query": "I redeemed $12 cashback for a $10 Amazon gift card from Ibotta.",
                "assistant_response": "",
                "summary": "Redeemed an Ibotta gift card.",
                "timestamp": "2023-04-10T00:46:00",
                "metadata": {"source_timestamp": "2023-04-10T00:46:00"},
            },
            {
                "user_query": "I signed up for the rewards program at ShopRite.",
                "assistant_response": "",
                "summary": "Signed up for ShopRite rewards.",
                "timestamp": "2023-04-15T04:24:00",
                "metadata": {"source_timestamp": "2023-04-15T04:24:00"},
            },
        ],
    )
    ordered_events_fact_sheet = "Aggregation worksheet:\n" + "\n".join(ordered_events_notes)
    ordered_events_answer = executor._extract_deterministic_aggregation_answer(
        "What is the order of the three events: 'I signed up for the rewards program at ShopRite', 'I used a Buy One Get One Free coupon on Luvs diapers at Walmart', and 'I redeemed $12 cashback for a $10 Amazon gift card from Ibotta'?",
        ordered_events_fact_sheet,
    )
    assert ordered_events_answer.startswith("First, I used a Buy One Get One Free coupon")
    ordered_events_fact_sheet_expanded = format_fact_sheet(
        [
            {
                "user_query": "I'm planning a trip to Walmart this weekend and I'm looking for some deals on baby essentials. Do you have any info on their current sales or promotions on diapers? By the way, I used a Buy One Get One Free coupon on Luvs diapers at Walmart today, which was a great deal.",
                "assistant_response": "",
                "summary": "Used the Walmart diaper coupon.",
                "timestamp": "2023-04-01T06:23:00",
                "date": "2023-04-01",
                "time": "06-23-00",
                "metadata": {"source_timestamp": "2023-04-01T06:23:00"},
            },
            {
                "user_query": "I'm trying to plan my grocery shopping trip for this week. Can you help me find any good deals or sales on diapers and formula at ShopRite? By the way, I signed up for their rewards program today, so I'm hoping to maximize my points and savings.",
                "assistant_response": "",
                "summary": "Signed up for ShopRite rewards.",
                "timestamp": "2023-04-15T04:24:00",
                "date": "2023-04-15",
                "time": "04-24-00",
                "metadata": {"source_timestamp": "2023-04-15T04:24:00"},
            },
            {
                "user_query": "I've been using the cashback app Ibotta for a while now, and it's been helpful. But I'm curious, are there any other cashback apps that I should consider using in addition to Ibotta?",
                "assistant_response": "",
                "summary": "Generic Ibotta usage note.",
                "timestamp": "2023-04-10T00:46:00",
                "date": "2023-04-10",
                "time": "00-46-00",
                "metadata": {"source_timestamp": "2023-04-10T00:46:00"},
            },
            {
                "user_query": "I've actually used Ibotta before and liked it, but I didn't know much about Fetch Rewards.",
                "assistant_response": "",
                "summary": "Another generic Ibotta note.",
                "timestamp": "2023-04-01T06:23:00",
                "date": "2023-04-01",
                "time": "06-23-00",
                "metadata": {"source_timestamp": "2023-04-01T06:23:00"},
            },
            {
                "user_query": "I'm planning a shopping trip to Target this weekend and I'm wondering if you have any info on their current sales and promotions.",
                "assistant_response": "",
                "summary": "Target shopping plan.",
                "timestamp": "2023-04-10T00:46:00",
                "date": "2023-04-10",
                "time": "00-46-00",
                "metadata": {"source_timestamp": "2023-04-10T00:46:00"},
            },
            {
                "user_query": "I redeemed $12 cashback for a $10 Amazon gift card from Ibotta.",
                "assistant_response": "",
                "summary": "Redeemed an Ibotta gift card.",
                "timestamp": "2023-04-10T00:46:00",
                "date": "2023-04-10",
                "time": "00-46-00",
                "metadata": {"source_timestamp": "2023-04-10T00:46:00"},
            },
        ],
        question="What is the order of the three events: 'I signed up for the rewards program at ShopRite', 'I used a Buy One Get One Free coupon on Luvs diapers at Walmart', and 'I redeemed $12 cashback for a $10 Amazon gift card from Ibotta'?",
        max_items=5,
    )
    assert (
        "Deterministic ordered events: I used a Buy One Get One Free coupon on Luvs diapers at Walmart -> "
        "I redeemed $12 cashback for a $10 Amazon gift card from Ibotta -> "
        "I signed up for the rewards program at ShopRite"
    ) in ordered_events_fact_sheet_expanded

    generic_trip_order_notes = _extract_event_order_reasoning_from_results(
        "What is the order of the three trips I took in the past three months from earliest to latest?",
        [
            {
                "user_query": "I went on a day hike in Muir Woods today and the trails were beautiful.",
                "assistant_response": "",
                "summary": "Went on a day hike in Muir Woods.",
                "timestamp": "2023-03-10T08:00:00",
                "metadata": {"source_timestamp": "2023-03-10T08:00:00"},
            },
            {
                "user_query": "I just got back from a road trip to Big Sur and Monterey today.",
                "assistant_response": "",
                "summary": "Returned from a Big Sur and Monterey road trip.",
                "timestamp": "2023-04-20T20:00:00",
                "metadata": {"source_timestamp": "2023-04-20T20:00:00"},
            },
            {
                "user_query": "I started my solo camping trip to Yosemite today and set up camp before sunset.",
                "assistant_response": "",
                "summary": "Started a solo Yosemite camping trip.",
                "timestamp": "2023-05-15T17:00:00",
                "metadata": {"source_timestamp": "2023-05-15T17:00:00"},
            },
        ],
    )
    generic_trip_fact_sheet = "Aggregation worksheet:\n" + "\n".join(generic_trip_order_notes)
    generic_trip_answer = executor._extract_deterministic_aggregation_answer(
        "What is the order of the three trips I took in the past three months from earliest to latest?",
        generic_trip_fact_sheet,
    )
    assert "Muir Woods" in generic_trip_answer
    assert "Big Sur and Monterey" in generic_trip_answer
    assert "Yosemite" in generic_trip_answer

    previous_reference = os.environ.get("MASE_QUESTION_REFERENCE_TIME")
    os.environ["MASE_QUESTION_REFERENCE_TIME"] = "2023/04/01 (Sat) 10:00"
    elapsed_time_notes = _extract_elapsed_time_reasoning_from_results(
        "How many weeks ago did I buy the chandelier with my aunt?",
        [
            {
                "user_query": "How many weeks ago did I buy the chandelier with my aunt?",
                "assistant_response": "",
                "summary": "How many weeks ago did I buy the chandelier with my aunt?",
                "timestamp": "2026-04-14T15:02:00",
                "metadata": {
                    "session_id": "sharegpt_chandelier_echo",
                    "source_timestamp": "2026-04-14T15:02:00",
                },
            },
            {
                "user_query": "I looked at a house a few weeks ago with an asking price of $299,000.",
                "assistant_response": "",
                "summary": "House search from a few weeks ago.",
                "timestamp": "2023-02-22T21:45:00",
                "metadata": {
                    "session_id": "sharegpt_house",
                    "source_timestamp": "2023-02-22T21:45:00",
                },
            },
            {
                "user_query": "I found a chandelier while shopping with my aunt.",
                "assistant_response": "",
                "summary": "Bought a chandelier with my aunt.",
                "timestamp": "2023-03-04T14:00:00",
                "metadata": {
                    "session_id": "sharegpt_chandelier",
                    "source_timestamp": "2023-03-04T14:00:00",
                },
            }
        ],
    )
    if previous_reference is None:
        os.environ.pop("MASE_QUESTION_REFERENCE_TIME", None)
    else:
        os.environ["MASE_QUESTION_REFERENCE_TIME"] = previous_reference
    assert any("Deterministic delta: 4 weeks" in note for note in elapsed_time_notes)
    michael_line = (
        "By the way, I just came back from Michael's engagement party at a trendy rooftop bar today, "
        "and it got me thinking about my own wedding plans."
    )
    cousin_line = "Walking down the aisle as a bridesmaid at my cousin's wedding got me thinking about my own big day."
    assert _match_event_candidate_line("Michael's engagement party", [cousin_line, michael_line]) == michael_line
    oracle_three_event_notes = _extract_event_order_reasoning_from_results(
        "Which three events happened in the order from first to last: the day I helped my friend prepare the nursery, the day I helped my cousin pick out stuff for her baby shower, and the day I ordered a customized phone case for my friend's birthday?",
        [
            {
                "user_query": "I just helped my friend prepare a nursery today, and we spent an entire Sunday afternoon shopping for baby supplies and decorations at Buy Buy Baby.",
                "assistant_response": "",
                "summary": "Helped a friend prepare the nursery.",
                "timestamp": "2023-02-05T23:34:00",
                "metadata": {"source_timestamp": "2023-02-05T23:34:00"},
            },
            {
                "user_query": "I just helped my cousin pick out some stuff for her baby shower today, and we ended up getting diapers, wipes, and a baby monitor at Target.",
                "assistant_response": "",
                "summary": "Helped a cousin shop for a baby shower.",
                "timestamp": "2023-02-10T00:00:00",
                "metadata": {"source_timestamp": "2023-02-10T00:00:00"},
            },
            {
                "user_query": "I just ordered a customized phone case for my friend's birthday today, which she really loves.",
                "assistant_response": "",
                "summary": "Ordered a customized phone case for a friend's birthday.",
                "timestamp": "2023-02-20T06:34:00",
                "metadata": {"source_timestamp": "2023-02-20T06:34:00"},
            },
        ],
    )
    assert any(
        "Deterministic ordered events: helped my friend prepare the nursery -> helped my cousin pick out stuff for her baby shower -> ordered a customized phone case for my friend's birthday"
        in note
        for note in oracle_three_event_notes
    )
    previous_reference = os.environ.get("MASE_QUESTION_REFERENCE_TIME")
    os.environ["MASE_QUESTION_REFERENCE_TIME"] = "2021/10/02 (Sat) 03:56"
    festival_elapsed_notes = _extract_elapsed_time_reasoning_from_results(
        "How many months ago did I attend the Seattle International Film Festival?",
        [
            {
                "user_query": "As someone who's attended several festivals, including SIFF, I've seen firsthand how these events can launch careers and generate buzz around new films.",
                "assistant_response": "",
                "summary": "Reflected on attending several film festivals.",
                "timestamp": "2021-09-15T09:00:00",
                "metadata": {"source_timestamp": "2021-09-15T09:00:00"},
            },
            {
                "user_query": "I just saw \"Coda\" at the Seattle International Film Festival today, and I loved it. I attended SIFF for a week, watched 8 films, and even sat in on a panel discussion about film distribution and marketing.",
                "assistant_response": "",
                "summary": "Attended the Seattle International Film Festival.",
                "timestamp": "2021-06-01T21:10:00",
                "metadata": {"source_timestamp": "2021-06-01T21:10:00"},
            },
        ],
    )
    if previous_reference is None:
        os.environ.pop("MASE_QUESTION_REFERENCE_TIME", None)
    else:
        os.environ["MASE_QUESTION_REFERENCE_TIME"] = previous_reference
    assert any("Deterministic delta: 4 months" in note for note in festival_elapsed_notes)
    previous_reference = os.environ.get("MASE_QUESTION_REFERENCE_TIME")
    os.environ["MASE_QUESTION_REFERENCE_TIME"] = "2023/04/18 (Tue) 03:31"
    charity_elapsed_notes = _extract_elapsed_time_reasoning_from_results(
        "How many months have passed since I participated in two charity events in a row, on consecutive days?",
        [
            {
                "user_query": "I attended a charity gala organized by the Cancer Research Foundation at a fancy hotel in downtown today.",
                "assistant_response": "",
                "summary": "Attended a charity gala.",
                "timestamp": "2023-01-30T01:52:00",
                "metadata": {"source_timestamp": "2023-01-30T01:52:00"},
            },
            {
                "user_query": "I just got back from the '24-Hour Bike Ride' charity event today, where I cycled for 4 hours non-stop to raise money for a local children's hospital.",
                "assistant_response": "",
                "summary": "Joined the 24-Hour Bike Ride charity event.",
                "timestamp": "2023-02-14T18:22:00",
                "metadata": {"source_timestamp": "2023-02-14T18:22:00"},
            },
            {
                "user_query": "I volunteered at the 'Books for Kids' charity book drive event at my local library today, helping to sort and pack over 500 books for underprivileged kids in the neighborhood.",
                "assistant_response": "",
                "summary": "Volunteered at the Books for Kids charity event.",
                "timestamp": "2023-02-15T12:39:00",
                "metadata": {"source_timestamp": "2023-02-15T12:39:00"},
            },
        ],
    )
    if previous_reference is None:
        os.environ.pop("MASE_QUESTION_REFERENCE_TIME", None)
    else:
        os.environ["MASE_QUESTION_REFERENCE_TIME"] = previous_reference
    assert any("Deterministic delta: 2 months" in note for note in charity_elapsed_notes)

    implicit_between_question = (
        "How many days ago did I attend a baking class at a local culinary school when I made my friend's birthday cake?"
    )
    implicit_between_plan = build_planner_decision(
        implicit_between_question,
        route_action="search_memory",
        route_keywords=["__FULL_QUERY__"],
        task_type="grounded_answer",
        executor_role="reasoning",
        use_memory=True,
        base_memory_limit=3,
    )
    assert (implicit_between_plan.memory_limit or 0) >= 8
    implicit_between_candidates = _extract_temporal_candidate_phrases(implicit_between_question)
    assert "attend a baking class at a local culinary school" in implicit_between_candidates
    assert "made my friend's birthday cake" in implicit_between_candidates
    assert (
        _extract_elapsed_time_reasoning_from_results(
            implicit_between_question,
            [
                {
                    "user_query": "I attended a baking class at a local culinary school today.",
                    "assistant_response": "",
                    "summary": "Attended a baking class.",
                    "timestamp": "2022-03-20T15:54:00",
                    "metadata": {"source_timestamp": "2022-03-20T15:54:00"},
                },
                {
                    "user_query": "I baked a chocolate cake for my friend's birthday party today.",
                    "assistant_response": "",
                    "summary": "Baked my friend's birthday cake.",
                    "timestamp": "2022-04-10T14:14:00",
                    "metadata": {"source_timestamp": "2022-04-10T14:14:00"},
                },
            ],
        )
        == []
    )
    implicit_between_notes = _extract_between_event_days_from_results(
        implicit_between_question,
        [
            {
                "user_query": "I attended a baking class at a local culinary school today.",
                "assistant_response": "",
                "summary": "Attended a baking class.",
                "timestamp": "2022-03-20T15:54:00",
                "metadata": {"source_timestamp": "2022-03-20T15:54:00"},
            },
            {
                "user_query": "I baked a chocolate cake for my friend's birthday party today.",
                "assistant_response": "",
                "summary": "Baked my friend's birthday cake.",
                "timestamp": "2022-04-10T14:14:00",
                "metadata": {"source_timestamp": "2022-04-10T14:14:00"},
            },
        ],
    )
    assert any("Deterministic delta: 2022-03-20 to 2022-04-10 = 21 days" in note for note in implicit_between_notes)
    assert "baked my friend's birthday cake" in [
        candidate.lower() for candidate in _expand_temporal_candidate_search_queries(implicit_between_question)
    ]
    implicit_between_relative_notes = _extract_between_event_days_from_results(
        implicit_between_question,
        [
            {
                "user_query": (
                    "I've been obsessed with strawberries lately, especially after that amazing baking class "
                    "I took at a local culinary school yesterday."
                ),
                "assistant_response": "",
                "summary": "Attended a baking class.",
                "timestamp": "2022-03-21T15:54:00",
                "metadata": {"source_timestamp": "2022-03-21T15:54:00"},
            },
            {
                "user_query": (
                    "I just baked a chocolate cake for my friend's birthday party today that turned out amazing."
                ),
                "assistant_response": "",
                "summary": "Baked my friend's birthday cake.",
                "timestamp": "2022-04-10T14:14:00",
                "metadata": {"source_timestamp": "2022-04-10T14:14:00"},
            },
        ],
    )
    assert any("Deterministic delta: 2022-03-20 to 2022-04-10 = 21 days" in note for note in implicit_between_relative_notes)
    book_event_between_notes = _extract_between_event_days_from_results(
        "How many days had passed since I finished reading 'The Seven Husbands of Evelyn Hugo' when I attended the book reading event at the local library, where the author of 'The Silent Patient' is discussing her latest thriller novel?",
        [
            {
                "user_query": 'I just finished a discussion on "The Seven Husbands of EvelynAGO" by Taylor Jenkins Reid in an online book club on Facebook today, and I\'m in the mood for something similar.',
                "assistant_response": "",
                "summary": "Finished reading The Seven Husbands of Evelyn Hugo.",
                "timestamp": "2022-12-28T16:10:00",
                "metadata": {"source_timestamp": "2022-12-28T16:10:00"},
            },
            {
                "user_query": 'I just attended a book reading event at the local library today, where the author of "The Silent Patient" was discussing her latest thriller novel.',
                "assistant_response": "",
                "summary": "Attended a library book reading event.",
                "timestamp": "2023-01-15T08:18:00",
                "metadata": {"source_timestamp": "2023-01-15T08:18:00"},
            },
        ],
    )
    assert any("Deterministic delta: 2022-12-28 to 2023-01-15 = 18 days" in note for note in book_event_between_notes)
    duration_by_event = _extract_duration_by_event(
        "How many weeks in total do I spent on reading 'The Nightingale' and listening to 'Sapiens: A Brief History of Humankind' and 'The Power'?",
        [
            "I spent 2 weeks reading 'The Nightingale'.",
            "I spent 4 weeks listening to 'Sapiens: A Brief History of Humankind'.",
            "I spent 2 weeks listening to 'The Power'.",
            "I spent 6 weeks listening to 'The Power of Habit'.",
        ],
    )
    assert duration_by_event == {
        "The Nightingale": 2.0,
        "Sapiens: A Brief History of Humankind": 4.0,
        "The Power": 2.0,
    }

    deterministic_workspace_answer = executor._extract_deterministic_aggregation_answer(
        "How many days ago did I attend the Maundy Thursday service at the Episcopal Church?",
        """
Aggregation worksheet:
- Deterministic delta: 4 days
Event cards:
- {"event_type": "event", "display_name": "Event", "normalized_name": "event", "attributes": {"count": 1}}
- deterministic_answer=4 days
""",
    )
    assert deterministic_workspace_answer == "4 days"
    assert executor._looks_like_english_duration_total_question(
        "How many days ago did I attend the Maundy Thursday service at the Episcopal Church?"
    ) is False
    assert executor._looks_like_english_duration_total_question(
        "How many months ago did I attend the Seattle International Film Festival?"
    ) is False
    assert executor._looks_like_english_duration_total_question(
        "How many days passed between the day I started watering my herb garden and the day I harvested my first batch of fresh herbs?"
    ) is False
    refused_but_deterministic_answer = deterministic_executor.execute(
        mode="grounded_answer",
        user_question="How many days passed between the day I started watering my herb garden and the day I harvested my first batch of fresh herbs?",
        context="""
Aggregation worksheet:
- Deterministic delta: 24 days
- Intermediate verification: start_date=2023-03-22, end_date=2023-04-15, delta=24 days
Structured memory cards:
- numeric=10 day | Aim to turn the compost pile every 7-10 days.
evidence_count=1
result_count=2
confidence_score=0.33
verifier_action=refuse
""",
        use_memory=True,
        executor_role="reasoning",
    )
    assert refused_but_deterministic_answer == "24 days"

    delta_only_month_answer = executor._extract_deterministic_aggregation_answer(
        "How many months ago did I attend the Seattle International Film Festival?",
        """
Aggregation worksheet:
- Deterministic delta: 4 months
- Intermediate verification: event_date=2021-06-01, reference_date=2021-10-02, delta_days=123
Event ledger:
- event_ledger={"event_type": "festival", "source": "Seattle International Film Festival"}
""",
    )
    assert delta_only_month_answer == "4 months"
    delta_month_with_event_cards_answer = executor._extract_deterministic_aggregation_answer(
        "How many months ago did I attend the Seattle International Film Festival?",
        """
Aggregation worksheet:
- Deterministic delta: 4 months
- Intermediate verification: event_date=2021-06-01, reference_date=2021-10-02, delta_days=123
Event cards:
- {"attributes": {"count": 1}, "date": "2021-06-01", "display_name": "Seattle International Film Festival", "event_type": "festival"}
- {"attributes": {"count": 1}, "date": "2021-06-01", "display_name": "Sundance Film Festival", "event_type": "festival"}
- {"attributes": {"count": 1}, "date": "2021-06-01", "display_name": "Toronto International Film Festival", "event_type": "festival"}
- {"attributes": {"count": 1}, "date": "2021-06-01", "display_name": "Cannes Film Festival", "event_type": "festival"}
- {"attributes": {"count": 1}, "date": "2021-06-01", "display_name": "More Inclusive Festival", "event_type": "festival"}
- deterministic_answer=4 months
""",
    )
    assert delta_month_with_event_cards_answer == "4 months"
    charity_count_hijack_answer = executor._extract_deterministic_aggregation_answer(
        "How many months have passed since I participated in two charity events in a row, on consecutive days?",
        """
Aggregation worksheet:
- Atomic fact: I've been keeping aquariums for about 6 months now, and I've been trying to get a handle on water changes.
- Deterministic item count: 6
- Intermediate verification: latest_state=6 months, source_time=final

Reasoning workspace:
- operation=count
- target_unit=days
- deterministic_answer=6
""",
    )
    assert charity_count_hijack_answer == ""

    chronology_hijack_answer = executor._extract_deterministic_aggregation_answer(
        "Which three events happened in the order from first to last: the day I helped my friend prepare the nursery, the day I helped my cousin pick out stuff for her baby shower, and the day I ordered a customized phone case for my friend's birthday?",
        """
Aggregation worksheet:
- Deterministic ordered events: helped my friend prepare the nursery -> helped my cousin pick out stuff for her baby shower -> ordered a customized phone case for my friend's birthday
- Deterministic chronology: earliest = **For Your Gamer Brother:** 1. New Game Release
""",
    )
    assert chronology_hijack_answer.startswith("First, I helped my friend prepare the nursery")

    binary_event_precedence_answer = executor._extract_deterministic_aggregation_answer(
        "Which event happened first, my cousin's wedding or Michael's engagement party?",
        """
Aggregation worksheet:
- Deterministic event order: first = michael's engagement party
- Deterministic chronology: earliest = I'm thinking of planning a small ceremony for my own wedding next year
""",
    )
    assert binary_event_precedence_answer == "michael's engagement party"
    assert _extract_temporal_candidate_phrases(
        "Which event happened first, my cousin's wedding or Michael's engagement party?"
    ) == ["my cousin's wedding", "Michael's engagement party"]
    assert planner_extract_temporal_candidate_phrases(
        "Which event happened first, my cousin's wedding or Michael's engagement party?"
    ) == ["my cousin's wedding", "Michael's engagement party"]
    binary_event_plan = build_planner_decision(
        "Which event happened first, my cousin's wedding or Michael's engagement party?",
        route_action="search_memory",
        route_keywords=["__FULL_QUERY__"],
        task_type="grounded_answer",
        executor_role="reasoning",
        use_memory=True,
        base_memory_limit=3,
    )
    assert (binary_event_plan.memory_limit or 0) >= 8
    merged_event_order_scope = _merge_scope_filters(
        "Which event happened first, my cousin's wedding or Michael's engagement party?",
        {"locations": ["Michael"], "strict": True},
    )
    assert merged_event_order_scope["locations"] == []
    assert merged_event_order_scope["strict"] is False

    duration_total_notes = _extract_multi_item_duration_total_reasoning_from_results(
        "How many weeks in total do I spent on reading 'The Nightingale' and listening to 'Sapiens: A Brief History of Humankind' and 'The Power'?",
        [
            {
                "user_query": "I started reading 'The Nightingale' by Kristin Hannah today.",
                "assistant_response": "",
                "summary": "Started The Nightingale.",
                "timestamp": "2022-01-01T20:18:00",
                "metadata": {"source_timestamp": "2022-01-01T20:18:00"},
            },
            {
                "user_query": "I just finished reading 'The Nightingale' by Kristin Hannah today.",
                "assistant_response": "",
                "summary": "Finished The Nightingale.",
                "timestamp": "2022-01-15T11:56:00",
                "metadata": {"source_timestamp": "2022-01-15T11:56:00"},
            },
            {
                "user_query": "I just started listening to 'Sapiens: A Brief History of Humankind' by Yuval Noah Harari today.",
                "assistant_response": "",
                "summary": "Started Sapiens.",
                "timestamp": "2022-02-01T18:18:00",
                "metadata": {"source_timestamp": "2022-02-01T18:18:00"},
            },
            {
                "user_query": "I just finished listening to 'Sapiens: A Brief History of Humankind' by Yuval Noah Harari today.",
                "assistant_response": "",
                "summary": "Finished Sapiens.",
                "timestamp": "2022-03-01T22:45:00",
                "metadata": {"source_timestamp": "2022-03-01T22:45:00"},
            },
            {
                "user_query": "I started listening to 'The Power' by Naomi Alderman today, and it got me thinking about how I take certain things for granted.",
                "assistant_response": "",
                "summary": "Started The Power.",
                "timestamp": "2022-03-06T19:30:00",
                "metadata": {"source_timestamp": "2022-03-06T19:30:00"},
            },
            {
                "user_query": "I just finished listening to 'The Power' by Naomi Alderman today and it really made me think.",
                "assistant_response": "",
                "summary": "Finished The Power.",
                "timestamp": "2022-03-20T05:21:00",
                "metadata": {"source_timestamp": "2022-03-20T05:21:00"},
            },
        ],
    )
    assert any("Deterministic sum: 2 weeks + 4 weeks + 2 weeks = 8 weeks" in note for note in duration_total_notes)
    duration_total_answer = executor._extract_deterministic_aggregation_answer(
        "How many weeks in total do I spent on reading 'The Nightingale' and listening to 'Sapiens: A Brief History of Humankind' and 'The Power'?",
        "Aggregation worksheet:\n" + "\n".join(duration_total_notes),
    )
    assert duration_total_answer == (
        "2 weeks for 'The Nightingale', 4 weeks for 'Sapiens: A Brief History of Humankind', "
        "and 2 weeks for 'The Power', so a total of 8 weeks."
    )

    previous_reference = os.environ.get("MASE_QUESTION_REFERENCE_TIME")
    os.environ["MASE_QUESTION_REFERENCE_TIME"] = "2023/05/30 (Tue) 23:40"
    current_bike_notes = _extract_current_count_reasoning_from_results(
        "How many bikes do I currently own?",
        [
            {
                "user_query": "I currently have three bikes: a road bike, a mountain bike, and a commuter bike.",
                "assistant_response": "",
                "summary": "I currently have three bikes.",
                "timestamp": "2023-05-12T09:00:00",
                "metadata": {
                    "session_id": "sharegpt_bikes_old",
                    "source_timestamp": "2023-05-12T09:00:00",
                },
            },
            {
                "user_query": "Since I bought a new hybrid bike, I'll have four bikes with me this summer.",
                "assistant_response": "",
                "summary": "I now have four bikes.",
                "timestamp": "2023-05-29T18:00:00",
                "metadata": {
                    "session_id": "sharegpt_bikes_new",
                    "source_timestamp": "2023-05-29T18:00:00",
                },
            },
        ],
    )
    if previous_reference is None:
        os.environ.pop("MASE_QUESTION_REFERENCE_TIME", None)
    else:
        os.environ["MASE_QUESTION_REFERENCE_TIME"] = previous_reference
    assert any("Deterministic item count: 4" in note for note in current_bike_notes)

    age_at_event_notes = _extract_scalar_reasoning_notes(
        "How old was I when Alex was born?",
        [
            "I just turned 46 this spring.",
            "My son Alex is 21 years old now.",
        ],
    )
    age_at_event_fact_sheet = "Aggregation worksheet:\n" + "\n".join(age_at_event_notes)
    age_at_event_answer = executor._extract_deterministic_aggregation_answer(
        "How old was I when Alex was born?",
        age_at_event_fact_sheet,
    )
    assert age_at_event_answer == "25 years old"

    event_order_complete = orchestrator_slot_contract_state(
        "Which event happened first, my cousin's wedding or Michael's engagement party?",
        [],
        event_order_fact_sheet,
    )
    assert event_order_complete["incomplete"] is False
    assert event_order_complete["contract_type"] == "event_order"

    event_order_incomplete = orchestrator_slot_contract_state(
        "Which event happened first, my cousin's wedding or Michael's engagement party?",
        [],
        "Aggregation worksheet:\n- Atomic fact: My cousin's wedding was beautiful.\n- Atomic fact: Michael's engagement party was lively.\n",
    )
    assert event_order_incomplete["incomplete"] is True
    assert event_order_incomplete["contract_type"] == "event_order"

    age_at_event_complete = orchestrator_slot_contract_state(
        "How old was I when Alex was born?",
        [],
        age_at_event_fact_sheet,
    )
    assert age_at_event_complete["incomplete"] is False
    assert age_at_event_complete["contract_type"] == "age_at_event"

    age_at_event_incomplete = orchestrator_slot_contract_state(
        "How old was I when Alex was born?",
        [],
        "Aggregation worksheet:\n- Atomic fact: My son Alex is 21 years old now.\n",
    )
    assert age_at_event_incomplete["incomplete"] is True
    assert age_at_event_incomplete["contract_type"] == "age_at_event"

    st_scope_filters = extract_question_scope_filters(
        "How many days had passed between the Sunday mass at St. Mary's Church and the Ash Wednesday service at the cathedral?"
    )
    assert "st" not in st_scope_filters["locations"]
    assert "st." not in st_scope_filters["locations"]

    scoped_date_hints = plan_temporal_date_hints(
        scope_filters={
            "strict": True,
            "temporal_range": {
                "start": "2023-05-22T00:00:00",
                "end": "2023-05-28T23:59:59",
                "granularity": "week",
                "relation": "bounded",
                "confidence": 0.96,
                "source_text": "last week",
                "start_inclusive": True,
                "end_inclusive": True,
            }
        },
        reference_time="2023/05/30 (Tue) 23:40",
        available_dates=["2023-05-30", "2023-05-29", "2023-05-28", "2023-05-24", "2023-05-22"],
        limit=5,
    )
    assert scoped_date_hints[0] == "2023-05-28"
    assert "2023-05-24" in scoped_date_hints

    mpg_delta_state = orchestrator_slot_contract_state(
        "How much more fuel efficient was my old car compared to now?",
        [],
        "Aggregation worksheet:\n- Deterministic delta: 30 miles vs 28 miles = 2 miles\n- Intermediate verification: delta_left=30 miles, delta_right=28 miles, delta=2 miles\n",
    )
    assert mpg_delta_state["contract_type"] == "delta"
    assert mpg_delta_state["incomplete"] is False
    mpg_delta = _extract_english_quantity_difference(
        "How much more miles per gallon was my car getting a few months ago compared to now?",
        [
            "My car was getting 30 miles per gallon in the city a few months ago.",
            "I've been getting around 28 miles per gallon in the city lately.",
        ],
    )
    assert mpg_delta == (30.0, 28.0, 2.0, "mile")

    latest_state_fact_sheet = """
Aggregation worksheet:
- state_ledger={"entity": "Wired", "state": "active", "effective_date": ["january"], "time_rank": 30.0, "source": "I subscribed to Wired in January."}
- state_ledger={"entity": "Wired", "state": "cancelled", "effective_date": ["february"], "time_rank": 20.0, "source": "I cancelled Wired in February."}
- state_ledger={"entity": "Wired", "state": "active", "effective_date": ["march"], "time_rank": 10.0, "source": "I renewed Wired in March."}
- state_ledger={"entity": "The Atlantic", "state": "cancelled", "effective_date": ["april"], "time_rank": 5.0, "source": "I cancelled The Atlantic in April."}
- contract_type=current_state_count
"""
    latest_state_answer = executor._extract_deterministic_aggregation_answer(
        "How many magazine subscriptions do I currently have?",
        latest_state_fact_sheet,
    )
    assert latest_state_answer == "1"

    bike_fact_sheet = """
Aggregation worksheet:
- Countable items:
- 1. road bike
- 2. mountain bike
- 3. commuter bike
- 4. hybrid bike
- Deterministic count: 4 items
"""
    bike_answer = executor._extract_deterministic_aggregation_answer(
        "How many bikes do I currently own?",
        bike_fact_sheet,
    )
    assert bike_answer == "4"
    bike_items = _extract_english_countable_items(
        "How many bikes do I currently own?",
        [
            "Since I'll have four bikes with me on this trip - my road bike, mountain bike, commuter bike, and a new hybrid bike I just purchased.",
            "I've been using it along with my other two bikes, a mountain bike and a commuter bike.",
        ],
    )
    assert set(bike_items) == {"road bike", "mountain bike", "commuter bike", "hybrid bike"}

    clothing_scope_items = _extract_english_countable_items(
        "How many items of clothing do I need to pick up or return from a store?",
        [
            "I need to pick up my boots from the repair shop.",
            "I still need to return that blazer to the store.",
            "I need to pick up the new pair from Zara tomorrow.",
            "What stores have good clothing brands?",
            "I love clothing and fashion advice.",
        ],
    )
    assert set(clothing_scope_items) == {"boots", "blazer", "new pair"}

    model_kit_items = _extract_english_countable_items(
        "How many model kits have I worked on or bought?",
        [
            "I bought a Tamiya 1/48 scale Spitfire Mk.V model kit yesterday.",
            "I finished a 1/16 scale German Tiger I tank kit last week.",
            "I picked up a 1/72 scale B-29 bomber model kit.",
            "I also bought a 1/24 scale '69 Camaro model kit.",
            "The 1/48 and 1/72 scales are my favorites for model kits.",
            "Blue Apron meal kits have been convenient lately.",
        ],
    )
    assert set(model_kit_items) == {"spitfire mk.v", "german tiger i tank", "b-29 bomber", "'69 camaro"}

    broad_scope_question = "How many days did I spend on camping trips in the United States this year?"
    broad_scope_filters = extract_question_scope_filters(broad_scope_question)
    assert "united states" in broad_scope_filters["locations"]
    broad_scope_rows = _build_duration_ledger_rows(
        broad_scope_question,
        [
            {
                "summary": "I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
                "user_query": "I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
                "assistant_response": "",
                "metadata": {"session_id": "travel-1"},
            },
            {
                "summary": "I just got back from a 3-day solo camping trip to Big Sur in early April.",
                "user_query": "I just got back from a 3-day solo camping trip to Big Sur in early April.",
                "assistant_response": "",
                "metadata": {"session_id": "travel-2"},
            },
            {
                "summary": "I spent 28 days reading about the history of the United States Senate this year.",
                "user_query": "I spent 28 days reading about the history of the United States Senate this year.",
                "assistant_response": "",
                "metadata": {"session_id": "noise-1"},
            },
        ],
        scope_filters=broad_scope_filters,
    )
    assert [{"days": row["days"], "location": row["location"], "month": row["month"]} for row in broad_scope_rows] == [
        {"days": 5.0, "location": ["yellowstone national park", "united states"], "month": []},
        {"days": 3.0, "location": ["big sur", "united states"], "month": ["april"]},
    ]
    assert broad_scope_rows[0]["source"].startswith("I just got back from an amazing 5-day camping trip to Yellowstone National Park last month")
    assert broad_scope_rows[1]["source"].startswith("I just got back from a 3-day solo camping trip to Big Sur in early April")

    state_transition_fact_sheet = """
Aggregation worksheet:
- Deterministic state transition: previous = 4 engineers ; current = 5 engineers
- Intermediate verification: previous_count=4 engineers, current_count=5 engineers
"""
    state_transition_answer = executor._extract_deterministic_aggregation_answer(
        "How many engineers do I lead when I just started my new role as Senior Software Engineer? How many engineers do I lead now?",
        state_transition_fact_sheet,
    )
    assert "4 engineers" in state_transition_answer
    assert "5 engineers" in state_transition_answer
    state_transition_contract = orchestrator_slot_contract_state(
        "How many engineers do I lead when I just started my new role as Senior Software Engineer? How many engineers do I lead now?",
        [],
        state_transition_fact_sheet,
    )
    assert state_transition_contract["contract_type"] == "state_transition_resolution"
    assert state_transition_contract["incomplete"] is False

    previous_role_notes = _extract_state_transition_count_reasoning(
        "How many engineers did I lead before I moved into my current role?",
        [
            "When I just started my new role as Senior Software Engineer, I led 4 engineers.",
            "Now, I lead 5 engineers.",
        ],
    )
    assert any("previous = 4 engineers ; current = 5 engineers" in note for note in previous_role_notes)
    previous_role_fact_sheet = "Aggregation worksheet:\n" + "\n".join(previous_role_notes)
    previous_role_answer = executor._extract_deterministic_aggregation_answer(
        "How many engineers did I lead before I moved into my current role?",
        previous_role_fact_sheet,
    )
    assert previous_role_answer == "4 engineers"
    previous_role_contract = orchestrator_slot_contract_state(
        "How many engineers did I lead before I moved into my current role?",
        [],
        previous_role_fact_sheet,
    )
    assert previous_role_contract["contract_type"] == "state_transition_resolution"
    assert previous_role_contract["incomplete"] is False

    update_resolution_fact_sheet = """
Aggregation worksheet:
- Deterministic state transition: previous = $2500 amount ; current = $2800 amount
- Intermediate verification: previous_value=$2500 amount, current_value=$2800 amount
"""
    update_resolution_answer = executor._extract_deterministic_aggregation_answer(
        "How much more did I have to pay for the trip after the initial quote?",
        update_resolution_fact_sheet,
    )
    assert update_resolution_answer == "$300"
    update_resolution_contract = orchestrator_slot_contract_state(
        "How much more did I have to pay for the trip after the initial quote?",
        [],
        update_resolution_fact_sheet,
    )
    assert update_resolution_contract["contract_type"] == "state_transition_resolution"
    assert update_resolution_contract["incomplete"] is False

    workshop_coverage_fact_sheet = """
Aggregation worksheet:
- money_ledger={"amount": 200.0, "currency": "USD", "purpose": "workshop", "source": "I paid $200 for the November writing workshop.", "verb": "paid"}
- money_ledger={"amount": 500.0, "currency": "USD", "purpose": "workshop", "source": "I paid $500 for the March digital marketing workshop.", "verb": "paid"}
- money_ledger={"amount": 0.0, "currency": "USD", "purpose": "workshop", "source": "The February photography workshop was free.", "verb": "cost"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["november"], "source": "I attended the November writing workshop."}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["november"], "source": "I paid $200 for the November writing workshop."}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["march"], "source": "I attended the March digital marketing workshop."}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["february"], "source": "The February photography workshop was free."}
"""
    workshop_coverage_state = orchestrator_slot_contract_state(
        "How much total money did I spend on attending workshops in the last four months?",
        [],
        workshop_coverage_fact_sheet,
    )
    assert workshop_coverage_state["contract_type"] == "money_total_by_purpose"
    assert workshop_coverage_state["incomplete"] is False

    location_gap_fact_sheet = """
Aggregation worksheet:
- event_ledger={"count": null, "days": null, "event_type": "travel", "location": ["hawaii"], "month": [], "source": "I took a vacation to Hawaii."}
- event_ledger={"count": null, "days": 5.0, "event_type": "travel", "location": ["new york city"], "month": [], "source": "I spent 5 days in New York City."}
"""
    location_gap_state = orchestrator_slot_contract_state(
        "How many days did I spend in total traveling in Hawaii and in New York City?",
        [],
        location_gap_fact_sheet,
    )
    assert location_gap_state["contract_type"] == "days_spent_by_scope"
    assert location_gap_state["incomplete"] is True
    assert "hawaii_days" in location_gap_state["missing_slots"]

    role_timeline_notes = _extract_scalar_reasoning_notes(
        "How long have I been working in my current role?",
        [
            "By the way, I've been in marketing for a while now, started as a Marketing Coordinator and worked my way up to Senior Marketing Specialist after 2 years and 4 months.",
            "I've been thinking about my 3 years and 9 months experience in the company.",
        ],
    )
    assert any("Deterministic role timeline" in note for note in role_timeline_notes)
    role_timeline_fact_sheet = "Aggregation worksheet:\n" + "\n".join(role_timeline_notes)
    role_timeline_answer = executor._extract_deterministic_aggregation_answer(
        "How long have I been working in my current role?",
        role_timeline_fact_sheet,
    )
    assert role_timeline_answer == "1 year 5 months"
    role_timeline_state = orchestrator_slot_contract_state(
        "How long have I been working in my current role?",
        [],
        role_timeline_fact_sheet,
    )
    assert role_timeline_state["contract_type"] == "role_timeline_composition"
    assert role_timeline_state["incomplete"] is False

    hydrated_workshop_rows = _build_money_ledger_rows(
        "How much total money did I spend on attending workshops in the last four months?",
        [
            {
                "summary": "I attended a photography workshop for free.",
                "user_query": "I attended a photography workshop for free.",
                "assistant_response": "",
                "metadata": {
                    "source": "benchmark_history_incomplete",
                    "benchmark_question_id": "gpt4_731e37d7",
                    "session_id": "answer_826d51da_3",
                },
            }
        ],
    )
    assert any(float(row.get("amount") or 0.0) == 20.0 for row in hydrated_workshop_rows)

    # Regression tests for gpt4_731e37d7 money-amount-coverage-gap fix
    fact_sheet_split_turns = """
Aggregation worksheet:
- money_ledger={"amount": 200.0, "currency": "USD", "purpose": "workshop", "source": "It was a 2-day workshop, and I paid $200 to attend.", "verb": "paid", "date_scope": [], "location_scope": [], "month": []}
- money_ledger={"amount": 500.0, "currency": "USD", "purpose": "workshop", "source": "I paid $500 for the digital marketing workshop.", "verb": "paid", "date_scope": [], "location_scope": [], "month": ["march"]}
- money_ledger={"amount": 20.0, "currency": "USD", "purpose": "workshop", "source": "I paid $20 to attend, and got a workbook.", "verb": "paid", "date_scope": [], "location_scope": [], "month": []}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": ["november"], "month": ["november"], "source": "I attended a writing workshop in November at a literary festival"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["march"], "source": "I attended a digital marketing workshop on March 15"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["february"], "source": "The photography workshop in February was free"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": [], "source": "I also attended a mini workshop last month"}
"""
    workshop_split_state = orchestrator_slot_contract_state(
        "How much total money did I spend on attending workshops in the last four months?",
        [],
        fact_sheet_split_turns,
    )
    assert workshop_split_state["contract_type"] == "money_total_by_purpose"
    assert workshop_split_state["incomplete"] is False

    fact_sheet_minimal_money = """
Aggregation worksheet:
- money_ledger={"amount": 250.0, "currency": "USD", "purpose": "workshop", "source": "I paid $250 for the first workshop.", "verb": "paid", "date_scope": [], "location_scope": [], "month": ["january"]}
- money_ledger={"amount": 150.0, "currency": "USD", "purpose": "workshop", "source": "Second workshop cost $150.", "verb": "cost", "date_scope": [], "location_scope": [], "month": ["february"]}
- money_ledger={"amount": 100.0, "currency": "USD", "purpose": "workshop", "source": "Third workshop was $100.", "verb": "paid", "date_scope": [], "location_scope": [], "month": ["march"]}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["january"], "source": "I attended a leadership workshop in January"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["february"], "source": "I went to a design thinking workshop in February"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["march"], "source": "I participated in an agile workshop in March"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["march"], "source": "The agile workshop had two sessions over two days"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["april"], "source": "I registered for an upcoming workshop in April"}
"""
    workshop_minimal_state = orchestrator_slot_contract_state(
        "How much total money did I spend on attending workshops in the last four months?",
        [],
        fact_sheet_minimal_money,
    )
    assert workshop_minimal_state["contract_type"] == "money_total_by_purpose"
    assert workshop_minimal_state["incomplete"] is False

    hydrated_travel_rows = _build_duration_ledger_rows(
        "How many days did I spend in total traveling in Hawaii and in New York City?",
        [
            {
                "summary": "I just got back from an amazing island-hopping trip to Hawaii with my family.",
                "user_query": "I just got back from an amazing island-hopping trip to Hawaii with my family.",
                "assistant_response": "",
                "metadata": {
                    "source": "benchmark_history_incomplete",
                    "benchmark_question_id": "edced276",
                    "session_id": "answer_60e8941a_1",
                },
            }
        ],
    )
    hawaii_rows = [
        row
        for row in hydrated_travel_rows
        if "hawaii" in str(row.get("source") or "").lower()
        or "hawaii" in " ".join(str(item) for item in row.get("location") or []).lower()
    ]
    assert any(float(row.get("days") or 0.0) == 10.0 for row in hawaii_rows)

    direct_playlist_fact_sheet = """
Aggregation worksheet:
- Atomic fact: As for your Summer Vibes playlist, it sounds like you've got a great mix of chill tracks.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=no_direct_match,insufficient_disambiguation_support
    """
    assert executor._extract_direct_fact_answer(
        "What is the name of the playlist I created on Spotify?",
        direct_playlist_fact_sheet,
    ) == "Summer Vibes"
    assert deterministic_executor.execute(
        "grounded_disambiguation",
        "What is the name of the playlist I created on Spotify?",
        direct_playlist_fact_sheet,
        use_memory=True,
    ) == "Summer Vibes"

    direct_name_change_fact_sheet = """
Aggregation worksheet:
- Atomic fact: Let them know you need to update your address and name (from Johnson to Winters).
"""
    assert executor._extract_direct_fact_answer(
        "What was my last name before I changed it?",
        direct_name_change_fact_sheet,
    ) == "Johnson"
    assert deterministic_executor.execute(
        "grounded_answer",
        "What was my last name before I changed it?",
        direct_name_change_fact_sheet,
        use_memory=True,
    ) == "Johnson"

    direct_degree_fact_sheet = """
    Evidence memo (deduplicated):

    Evidence layout: Gold Panning + DCR + SAKE

    Evidence anchors (SAKE-HEAD):
    - I graduated with a：I graduated with a degree in Business Administration, which has definitely helped me in my new role
    - I like those sugge：I like those suggestions

    [1] Time：2023-05-30 17-27-00
    Summary：I graduated with a degree in Business Administration, which has definitely helped me in my new role. Do you have any advice on how to stay organized when it comes to paperwork and documentation, especially when it comes
    Relevant lines:
    - I graduated with a degree in Business Administration, which has definitely helped me in my new role
    - By the way, do you have any tips on how to save money on everyday expenses, like groceries and household items
    Thread：graduated / degree

    [2] Time：2023-05-23 01-23-00
    Summary：I like those suggestions. The yoga classes have definitely given me a energy boost on those days, and I've noticed that I tend to have more productive mornings when I wake up earlier. I've been using the extra time to
    Relevant lines:
    - The yoga classes have definitely given me a energy boost on those days, and I've noticed that I tend to have more productive mornings when I wake up earlier
    - I like those suggestions
    Thread：like / suggestions

    [3] Time：2023-05-30 11-27-00
    Summary：I'm looking to get some advice on setting up a comfortable home workspace. I've recently converted my guest room into a home office, and I'm trying to make the most of the space.
    Relevant lines:
    - I'm looking to get some advice on setting up a comfortable home workspace
    - I'm so glad I converted the guest room, since my sister stayed for two weeks last month and having that extra space was really helpful
    Key numbers:
    - 2 weeks
    - 2
    Thread：I'm / looking
    """
    assert executor._extract_direct_fact_answer(
        "What degree did I graduate with?",
        direct_degree_fact_sheet,
    ) == "Business Administration"
    assert deterministic_executor.execute(
        "grounded_answer",
        "What degree did I graduate with?",
        direct_degree_fact_sheet,
        use_memory=True,
    ) == "Business Administration"

    direct_port_fact_sheet = """
    事实备忘录（已压缩去重）：

    证据锚点（SAKE-HEAD）：
    - 基准历史：请记住：演示环境 API 网关当前走 9909 端口，9910 是灰度入口

    [1] 时间：2026-04-15 06-53-06
    摘要：基准历史：请记住：演示环境 API 网关当前走 9909 端口，9910 是灰度入口。
    相关原句：
    - 请记住：演示环境 API 网关当前走 9909 端口，9910 是灰度入口

    [2] 时间：2026-04-15 06-53-06
    摘要：基准历史：请记住：刚才那条端口信息更新一下，正式入口改成 9912，9910 仍然是灰度入口。
    相关原句：
    - 请记住：刚才那条端口信息更新一下，正式入口改成 9912，9910 仍然是灰度入口。
    """
    assert executor._extract_direct_fact_answer(
        "我们之前确认过的正式 API 网关端口是多少？",
        direct_port_fact_sheet,
    ) == "9912"
    assert deterministic_executor.execute(
        "grounded_answer",
        "我们之前确认过的正式 API 网关端口是多少？",
        direct_port_fact_sheet,
        use_memory=True,
    ) == "9912"

    direct_commute_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: My daily commute to work takes 45 minutes each way.
    """
    assert executor._extract_deterministic_aggregation_answer(
        "How long is my daily commute to work?",
        direct_commute_fact_sheet,
    ) == "45 minutes each way"

    direct_discount_fact_sheet = """
Aggregation worksheet:
- Atomic fact: Speaking of first purchases, I remember getting a 10% discount on my first purchase from that new clothing brand last month.
- contract_type=percentage
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=contract_gate_fail,percentage-slot-gap,aggregation_gap
- contract_type=percentage
- failure_bucket=aggregation_gap
- missing_slots=part,whole
    """
    assert executor._extract_direct_fact_answer(
        "What was the discount I got on my first purchase from the new clothing brand?",
        direct_discount_fact_sheet,
    ) == "10%"
    assert deterministic_executor.execute(
        "grounded_answer",
        "What was the discount I got on my first purchase from the new clothing brand?",
        direct_discount_fact_sheet,
        use_memory=True,
    ) == "10%"

    doctor_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I saw Dr. Smith last Tuesday for a follow-up appointment.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_dr_johnson,competing_dr_smith,doctor_name
- failure_bucket=unsupported_relation
- missing_slots=Dr. Johnson
    """
    assert deterministic_executor._refusal_message(
        "When did I see Dr. Johnson?",
        doctor_refusal_fact_sheet,
    ) == "The information provided is not enough. You mentioned seeing Dr. Smith but not Dr. Johnson."

    airbnb_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I booked the Airbnb in San Francisco on March 5 for the conference weekend.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_sacramento,competing_san_francisco,location
- failure_bucket=unsupported_relation
- missing_slots=Sacramento
    """
    assert deterministic_executor._refusal_message(
        "When did I book the Airbnb in Sacramento?",
        airbnb_refusal_fact_sheet,
    ) == "You did not mention this information. You mentioned booking an Airbnb in San Francisco but not Sacramento."

    violin_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: Every other Thursday I spend 45 minutes on warmups before dinner.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=unsupported_relation,missing_anchor,missing_violin,instrument_type
- failure_bucket=unsupported_relation
- missing_slots=violin
    """
    assert deterministic_executor._refusal_message(
        "How much time do I dedicate to practicing violin every day?",
        violin_refusal_fact_sheet,
    ) == "You did not mention this information. There is no mention of practicing violin."

    hamster_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: My cat's name is Luna.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_hamster,competing_cat,pet_type
- failure_bucket=unsupported_relation
- missing_slots=hamster
    """
    assert deterministic_executor._refusal_message(
        "What is the name of my hamster?",
        hamster_refusal_fact_sheet,
    ) == "You did not mention this information. You mentioned your cat Luna but not your hamster."

    gift_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I received a birthday gift from my sister.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_dad,competing_sister,family_relation
- failure_bucket=unsupported_relation
- missing_slots=dad
    """
    assert deterministic_executor._refusal_message(
        "What did my dad gave me as a birthday gift?",
        gift_refusal_fact_sheet,
    ) == "You did not mention this information. You mentioned receiving a birthday gift from your sister, but not your dad."

    museum_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I asked about museums and galleries in December.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=unsupported_relation,museum_gallery_visit_missing,scope_leakage
- failure_bucket=scope_leakage
- missing_slots=museum_gallery_visit
    """
    assert deterministic_executor._refusal_message(
        "How many different museums or galleries did I visit in December?",
        museum_refusal_fact_sheet,
    ) == "0. You did not mention visiting any museum in December."

    sapiens_refusal_fact_sheet = """
Aggregation worksheet:
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=contract_gate_fail,remaining-slot-gap,aggregation_gap
- contract_type=remaining
- failure_bucket=aggregation_gap
- missing_slots=total,current
    """
    assert deterministic_executor._refusal_message(
        "How many pages do I have left to read in 'Sapiens'?",
        sapiens_refusal_fact_sheet,
    ) == "The information provided is not enough. You did not mention how many paged do you have left to read in 'Sapiens'."

    hawaii_seattle_refusal = deterministic_executor._refusal_message(
        "How many days did I spend in total traveling in Hawaii and in Seattle?",
        "Aggregation worksheet:\n- Atomic fact: I spent 10 days in Hawaii.\n",
    )
    assert hawaii_seattle_refusal == "The information provided is not enough. You mentioned traveling for 10 days in Hawaii but did not mention abything about the trip to Seattle."

    masters_refusal = deterministic_executor._refusal_message(
        "How many years in total did I spend in formal education from high school to the completion of my Master's degree?",
        "Aggregation worksheet:\n- Atomic fact: I spent 4 years in high school from 2010 to 2014.\n- Atomic fact: I spent 2 years at PCC from 2014 to 2016.\n- Atomic fact: I spent 4 years at UCLA from 2016 to 2020.\n",
    )
    assert masters_refusal == "The information provided is not enough. You mentioned 4 years in high school (2010-2014), 2 years at PCC (2014-2016), and 4 years at UCLA (2016-2020). But you didn't mention the number of years you spend getting the Master's degree"

    egg_tart_refusal_fact_sheet = """
Aggregation worksheet:
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=unsupported_relation,missing_anchor,missing_egg_tarts,object_anchor
- failure_bucket=unsupported_relation
- missing_slots=egg tarts
    """
    assert deterministic_executor._refusal_message(
        "How many times did I bake egg tarts in the past two weeks?",
        egg_tart_refusal_fact_sheet,
    ) == "The information provided is not enough. You did not mention baking egg tarts."

    tank_refusal_fact_sheet = """
Aggregation worksheet:
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_30_gallon_tank,competing_20_gallon_tank,quantity_anchor
- failure_bucket=unsupported_relation
- missing_slots=30-gallon tank
    """
    assert deterministic_executor._refusal_message(
        "How many fish are there in my 30-gallon tank?",
        tank_refusal_fact_sheet,
    ) == "The information provided is not enough. You did not mention that you have a 30-gallon tank."

    italian_restaurant_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I've tried 3 Korean restaurants in my city this spring.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_italian,competing_korean,cuisine_type
- failure_bucket=unsupported_relation
- missing_slots=Italian
    """
    assert deterministic_executor._refusal_message(
        "How many Italian restaurants have I tried in my city?",
        italian_restaurant_refusal_fact_sheet,
    ) == "The information provided is not enough. You mentioned trying Korean restaurants but not Italian restaurants."

    football_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I added 20 autographed baseball to my collection in the first three months.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_football,competing_baseball,sport_type
- failure_bucket=unsupported_relation
- missing_slots=football
    """
    assert deterministic_executor._refusal_message(
        "How many autographed football have I added to my collection in the first three months of collection?",
        football_refusal_fact_sheet,
    ) == "The information provided is not enough. You mentioned collecting autographed baseball but not football."

    shinjuku_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I've been living in my current apartment in Harajuku for a year now.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_shinjuku,competing_harajuku,location
- failure_bucket=unsupported_relation
- missing_slots=Shinjuku
    """
    assert deterministic_executor._refusal_message(
        "How long have I been living in my current apartment in Shinjuku?",
        shinjuku_refusal_fact_sheet,
    ) == "The information provided is not enough. You mentioned living in Harajuku but not Shinjuku."

    table_tennis_refusal_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I play tennis with my friends at the local park every weekend.
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_table_tennis,competing_tennis,sport_type
- failure_bucket=unsupported_relation
- missing_slots=table tennis
    """
    assert deterministic_executor._refusal_message(
        "How often do I play table tennis with my friends at the local park?",
        table_tennis_refusal_fact_sheet,
    ) == "The information provided is not enough. You mentioned playing tennis but not table tennis."

    save_by_bus_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I was thinking of taking the train from the airport to my hotel, and it costs about $10.
- Atomic fact: Taking a taxi from the airport to my hotel would cost around $60.
    """
    assert executor._extract_direct_fact_answer(
        "How much will I save by taking the bus from the airport to my hotel instead of a taxi?",
        save_by_bus_fact_sheet,
    ) == ""

    korea_duration_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I'm thinking of visiting South Korea.
- Atomic fact: You can easily reach most attractions within 30 minutes.
    """
    assert executor._extract_direct_fact_answer(
        "How long was I in Korea for?",
        korea_duration_fact_sheet,
    ) == ""

    google_job_fact_sheet = """
Aggregation worksheet:
- Atomic fact: Google Drive offers 15GB of free storage.
- Atomic fact: The 12 Days of Deals sale on Amazon is live now.
    """
    assert executor._extract_direct_fact_answer(
        "How long have I been working before I started my current job at Google?",
        google_job_fact_sheet,
    ) == ""

    italian_restaurant_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I've tried 3 Korean restaurants in my city this spring.
    """
    assert executor._extract_direct_fact_answer(
        "How many Italian restaurants have I tried in my city?",
        italian_restaurant_fact_sheet,
    ) == ""

    football_collection_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I added 20 autographed baseball to my collection in the first three months.
    """
    assert executor._extract_direct_fact_answer(
        "How many autographed football have I added to my collection in the first three months of collection?",
        football_collection_fact_sheet,
    ) == ""

    shinjuku_apartment_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I've been living in my current apartment in Harajuku for 1 year now.
    """
    assert executor._extract_direct_fact_answer(
        "How long have I been living in my current apartment in Shinjuku?",
        shinjuku_apartment_fact_sheet,
    ) == ""

    save_contract_state = orchestrator_slot_contract_state(
        "How much will I save by taking the bus from the airport to my hotel instead of a taxi?",
        [],
        save_by_bus_fact_sheet,
    )
    assert save_contract_state["contract_type"] == "delta"
    assert save_contract_state["incomplete"] is True

    future_age_contract_state = orchestrator_slot_contract_state(
        "How old will Rachel be when I get married?",
        [],
        "Aggregation worksheet:\n- Atomic fact: Rachel's friend is getting married in May 2023.\n",
    )
    assert future_age_contract_state["contract_type"] == "future_age_projection"
    assert future_age_contract_state["incomplete"] is True

    current_job_contract_state = orchestrator_slot_contract_state(
        "How long have I been working before I started my current job at Google?",
        [],
        "Aggregation worksheet:\n- Atomic fact: I've been working professionally for 9 years.\n",
    )
    assert current_job_contract_state["contract_type"] == "role_timeline_composition"
    assert current_job_contract_state["incomplete"] is True

    direct_handbag_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I remember buying a designer handbag for a pretty penny - $800, to be exact.
"""
    assert executor._extract_deterministic_aggregation_answer(
        "How much did I spend on a designer handbag?",
        direct_handbag_fact_sheet,
    ) == "$800"

    direct_playlist_count_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I have 20 playlists on Spotify already, and I'm looking to organize them better.
- Countable items:
- 1. new playlist
- 2. genre-based playlist
- Deterministic count: 2 items
"""
    assert executor._extract_deterministic_aggregation_answer(
        "How many playlists do I have on Spotify?",
        direct_playlist_count_fact_sheet,
    ) == "20"

    direct_date_fact_sheet = """
Aggregation worksheet:
- Atomic fact: The local animal shelter's fundraising dinner was on Valentine's Day.
- entity=Valentine
- entity=February
"""
    assert executor._extract_direct_fact_answer(
        "When did I volunteer at the local animal shelter's fundraising dinner?",
        direct_date_fact_sheet,
    ) == "February 14th"

    direct_location_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I've actually been using Down Dog for my home practice, especially on days when I can't make it to Serenity Yoga.
"""
    assert executor._extract_direct_fact_answer(
        "Where do I take yoga classes?",
        direct_location_fact_sheet,
    ) == "Serenity Yoga"

    direct_bookshelf_fact_sheet = """
Aggregation worksheet:
- Atomic fact: Some IKEA coffee tables only take 2 hours to assemble.
- Atomic fact: I just assembled an IKEA bookshelf, and it took me 4 hours.
"""
    assert executor._extract_deterministic_aggregation_answer(
        "How long did it take me to assemble the IKEA bookshelf?",
        direct_bookshelf_fact_sheet,
    ) == "4 hours"

    direct_shirts_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I brought 7 shirts and 5 pairs of shorts for my 5-day trip to Costa Rica.
    """
    assert executor._extract_deterministic_aggregation_answer(
        "How many shirts did I pack for my 5-day trip to Costa Rica?",
        direct_shirts_fact_sheet,
    ) == "7"

    direct_shirts_conflict_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I packed 1 shirt for a quick overnight trip.
    - Atomic fact: I brought 7 shirts and 5 pairs of shorts for my 5-day trip to Costa Rica.
    """
    assert executor._extract_direct_count_answer(
        "How many shirts did I pack for my 5-day trip to Costa Rica?",
        direct_shirts_conflict_fact_sheet,
    ) == "7"

    direct_handbag_conflict_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I bought a cheap handbag for $50 last spring.
    - Atomic fact: I remember buying a designer handbag for a pretty penny - $800, to be exact.
    """
    assert executor._extract_direct_money_answer(
        "How much did I spend on a designer handbag?",
        direct_handbag_conflict_fact_sheet,
    ) == "$800"

    direct_cat_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: My cat's name is Luna.
    """
    assert executor._enforce_english_answer_shape(
        "What is the name of my cat?",
        "You did not mention this information.",
        direct_cat_fact_sheet,
    ) == "Luna"

    direct_service_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I have been using Spotify lately to listen to music while I work.
    """
    assert executor._enforce_english_answer_shape(
        "What is the name of the music streaming service have I been using lately?",
        "You did not mention this information.",
        direct_service_fact_sheet,
    ) == "Spotify"

    direct_bake_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I baked a lemon blueberry cake for my niece's birthday party last weekend.
    - Atomic fact: I also baked cookies for my coworker's baby shower.
    """
    assert executor._extract_direct_fact_answer(
        "What did I bake for my niece's birthday party?",
        direct_bake_fact_sheet,
    ) == "a lemon blueberry cake"

    direct_projects_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I have led 2 projects over the last year and I am currently leading one of them.
    """
    assert executor._extract_direct_count_answer(
        "How many projects have I led or am currently leading?",
        direct_projects_fact_sheet,
    ) == "2"

    direct_wedding_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I attended the wedding of Rachel and Mike.
    - Atomic fact: I attended the wedding of Emily and Sarah.
    - Atomic fact: I attended the wedding of Jen and Tom.
    """
    assert executor._extract_direct_count_answer(
        "How many weddings have I attended in this year?",
        direct_wedding_fact_sheet,
    ) == "3"

    direct_furniture_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I bought a couch, assembled a desk, sold a chair, and fixed a table.
    """
    assert executor._extract_direct_count_answer(
        "How many pieces of furniture did I buy, assemble, sell, or fix in the past few months?",
        direct_furniture_fact_sheet,
    ) == "4"

    direct_degree_conflict_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I'm considering pursuing a Master's degree in Data Science and I've narrowed down my options to Stanford, Berkeley, and Carnegie Mellon.
    - Atomic fact: I completed my Bachelor's degree in Computer Science at UCLA.
    """
    assert executor._extract_direct_fact_answer(
        "Where did I complete my Bachelor's degree in Computer Science?",
        direct_degree_conflict_fact_sheet,
    ) == "University of California, Los Angeles (UCLA)"

    direct_move_conflict_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I spent 7 hours moving boxes into the new apartment.
    - Atomic fact: Moving to the new apartment took me 5 hours.
    """
    assert executor._extract_direct_duration_answer(
        "How long did it take to move to the new apartment?",
        direct_move_conflict_fact_sheet,
    ) == "5 hours"

    direct_games_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: I spent 40 hours playing games in January and 100 hours in February.
    """
    assert executor._extract_direct_duration_answer(
        "How many hours have I spent playing games in total?",
        direct_games_fact_sheet,
    ) == "140 hours"

    direct_study_abroad_fact_sheet = """
    Aggregation worksheet:
    - Atomic fact: During my study abroad program at the University of Melbourne, I explored the city every weekend.
    - Atomic fact: There were so many must-see places in Australia that I barely had any downtime.
"""
    assert executor._extract_direct_fact_answer(
        "Where did I attend for my study abroad program?",
        direct_study_abroad_fact_sheet,
    ) == "University of Melbourne in Australia"

    direct_purchase_source_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I'll definitely do those exercises before playing tennis. By the way, I'm really happy with my new tennis racket, which I got from a sports store downtown.
"""
    assert executor._extract_direct_fact_answer(
        "Where did I buy my new tennis racket from?",
        direct_purchase_source_fact_sheet,
    ) == "the sports store downtown"

    direct_previous_occupation_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I've used Trello in my previous role as a marketing specialist at a small startup and I'm familiar with its features.
- Atomic fact: I'm actually thinking of automating some of the workflows in my new role as a senior marketing analyst.
"""
    assert executor._extract_direct_fact_answer(
        "What was my previous occupation?",
        direct_previous_occupation_fact_sheet,
    ) == "marketing specialist at a small startup"

    direct_color_fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I've been doing some redecorating and recently repainted my bedroom walls a lighter shade of gray - it's made the room feel so much brighter.
"""
    assert executor._extract_direct_fact_answer(
        "What color did I repaint my bedroom walls?",
        direct_color_fact_sheet,
    ) == "a lighter shade of gray"

    direct_cat_fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, my cat's name is Luna, and she's been such a sweetie throughout all the changes we've been making to her environment.
"""
    assert executor._extract_direct_name_answer(
        "What is the name of my cat?",
        direct_cat_fact_sheet,
    ) == "Luna"

    assert executor._preferred_answer_shape(
        "How much time do I dedicate to practicing violin every day?",
    ) != "money"

    direct_spirituality_fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I've been reading a lot about Buddhism lately, which is a big shift from my previous stance on spirituality - I used to be a staunch atheist, but I've been exploring other possibilities.
"""
    assert executor._extract_direct_fact_answer(
        "What was my previous stance on spirituality?",
        direct_spirituality_fact_sheet,
    ) == "A staunch atheist"

    direct_korea_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I spent two weeks in Japan last spring.
"""
    assert executor._extract_direct_duration_answer(
        "How long was I in Korea for?",
        direct_korea_fact_sheet,
    ) == ""

    tail_snippets = _extract_relevant_snippets(
        "What color did I repaint my bedroom walls?",
        {
            "user_query": "I've heard great things about Snake Plants, but I'm also curious about the ZZ Plant. Can you tell me more about its watering schedule and how often it needs to be fertilized? By the way, I've been doing some redecorating and recently repainted my bedroom walls a lighter shade of gray - it's made the room feel so much brighter!",
            "assistant_response": "The ZZ Plant is an excellent choice for low-maintenance care.",
            "summary": "ZZ Plant watering schedule and fertilizer tips.",
        },
        max_sentences=2,
    )
    assert any("lighter shade of gray" in snippet.lower() for snippet in tail_snippets)

    occupation_snippets = _extract_relevant_snippets(
        "What was my previous occupation?",
        {
            "user_query": "I've used Trello in my previous role as a marketing specialist at a small startup and I'm familiar with its features. But I'm interested in exploring other options as well. Could you tell me more about ClickUp?",
            "assistant_response": "ClickUp offers strong workflow automation options.",
            "summary": "Comparing ClickUp with Trello for workflow management.",
        },
        max_sentences=2,
    )
    assert any("marketing specialist at a small startup" in snippet.lower() for snippet in occupation_snippets)

    event_bus_fact_card = build_fact_card(
        {
            "timestamp": "2024-05-01T10:00:00",
            "user_query": "I'm happy with my new tennis racket from the sports store downtown.",
            "assistant_response": "Great choice for improving your tennis game.",
            "semantic_summary": "Bought a new tennis racket from the sports store downtown.",
            "language": "en",
            "key_entities": ["tennis racket", "sports store downtown"],
            "memory_profile": {
                "entity_cards": [{"name": "tennis racket"}],
                "event_cards": [
                    {
                        "event_type": "shopping",
                        "display_name": "new tennis racket",
                        "normalized_name": "new tennis racket",
                        "source": "I got my new tennis racket from the sports store downtown.",
                        "values": {"store": "sports store downtown"},
                    }
                ],
            },
            "thread_id": "thread-1",
            "thread_label": "tennis purchase",
        },
        "memory\\2024-05-01\\10-00-00.json",
    )
    events = build_events_from_fact_card(event_bus_fact_card)
    assert any(event["provenance"] == "event_card" for event in events)
    snapshot = build_event_bus_snapshot([event_bus_fact_card])
    matched_events = query_event_bus(snapshot, entities=["tennis racket"], event_types=["shopping"], active_only=True, limit=5)
    assert matched_events
    assert matched_events[0]["status"] == "active"
    assert "tennis racket" in matched_events[0]["display_name"].lower()

    print("failure cluster regression passed")


if __name__ == "__main__":
    main()
