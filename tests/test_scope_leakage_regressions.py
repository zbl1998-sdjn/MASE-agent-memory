from mase_tools.legacy import (
    _build_duration_ledger_rows,
    _extract_english_countable_items,
    _extract_scope_hints_from_text,
    _location_scope_matches_text,
    _should_use_query_variants_with_full_query,
    extract_question_scope_filters,
)
from memory_reflection import _build_scope_hints


def test_clothing_count_filters_generic_advice():
    items = _extract_english_countable_items(
        "How many items of clothing do I need to pick up or return from a store?",
        [
            "I need to pick up my boots from the repair shop.",
            "I still need to return that blazer to the store.",
            "I need to pick up the new pair from Zara tomorrow.",
            "What stores have good clothing brands?",
            "I love clothing and fashion advice.",
        ],
    )
    assert set(items) == {"boots", "blazer", "new pair"}


def test_model_kit_count_filters_scale_only_and_unrelated_kits():
    items = _extract_english_countable_items(
        "How many model kits have I worked on or bought?",
        [
            "I bought a Tamiya 1/48 scale Spitfire Mk.V model kit yesterday.",
            "I finished a 1/16 scale German Tiger I tank kit last week.",
            "I picked up a 1/72 scale B-29 bomber model kit.",
            "I also bought a 1/24 scale '69 Camaro model kit.",
            "The 1/48 and 1/72 scales are my favorites for model kits.",
            "Blue Apron meal kits have been convenient lately.",
            "This stock price prediction model still needs tuning.",
        ],
    )
    assert set(items) == {"spitfire mk.v", "german tiger i tank", "b-29 bomber", "'69 camaro"}


def test_united_states_scope_ignores_senate_noise():
    question = "How many days did I spend on camping trips in the United States this year?"
    scope_filters = extract_question_scope_filters(question)
    assert "united states" in scope_filters["locations"]
    assert _location_scope_matches_text("united states", "The United States Senate passed a bill.", []) is False

    rows = _build_duration_ledger_rows(
        question,
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
        scope_filters=scope_filters,
    )

    days = [row["days"] for row in rows]
    assert 5.0 in days and 3.0 in days
    assert any("united states" in [location.lower() for location in row["location"]] for row in rows)


def test_camping_days_scan_beyond_first_six_results_for_strict_scope():
    question = "How many days did I spend on camping trips in the United States this year?"
    scope_hints = _extract_scope_hints_from_text("By the way, I just got back from a 3-day solo camping trip to Big Sur in early April.")
    assert "united states" in [location.lower() for location in scope_hints["locations"]]
    rows = _build_duration_ledger_rows(
        question,
        [
            {
                "summary": "I spent 12 days reading about the history of the United States this year.",
                "user_query": "I spent 12 days reading about the history of the United States this year.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {"session_id": "noise-1"},
            },
            {
                "summary": "I spent 9 days planning a trip to the United States Senate museum this year.",
                "user_query": "I spent 9 days planning a trip to the United States Senate museum this year.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {"session_id": "noise-2"},
            },
            {
                "summary": "I spent 7 days on a business trip in Canada this year.",
                "user_query": "I spent 7 days on a business trip in Canada this year.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {"session_id": "noise-3"},
            },
            {
                "summary": "I spent 6 days on a beach vacation in Mexico this year.",
                "user_query": "I spent 6 days on a beach vacation in Mexico this year.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {"session_id": "noise-4"},
            },
            {
                "summary": "I spent 4 days on a hiking trip in Colorado this year.",
                "user_query": "I spent 4 days on a hiking trip in Colorado this year.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {"session_id": "noise-5"},
            },
            {
                "summary": "I spent 2 days on a camping trip in Oregon this year.",
                "user_query": "I spent 2 days on a camping trip in Oregon this year.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {"session_id": "noise-6"},
            },
            {
                "summary": "By the way, I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
                "user_query": "By the way, I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {"session_id": "travel-1"},
            },
            {
                "summary": "I just got back from a 3-day solo camping trip to Big Sur in early April.",
                "user_query": "I just got back from a 3-day solo camping trip to Big Sur in early April.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {"session_id": "travel-2"},
            },
        ],
    )
    days = [row["days"] for row in rows]
    assert 5.0 in days and 3.0 in days
    assert len(days) >= 3


def test_doctor_count_filters_generic_doctor_mentions():
    items = _extract_english_countable_items(
        "How many different doctors did I visit?",
        [
            "I had an appointment with my primary care physician for a checkup.",
            "I also saw an ENT specialist about my allergies.",
            "The dermatologist removed a suspicious mole.",
            "I need to find a new doctor soon.",
            "Here are questions to ask my doctor before the procedure.",
        ],
    )
    assert set(items) == {"primary care physician", "ent specialist", "dermatologist"}


def test_explicit_month_scope_does_not_inherit_timestamp_month():
    hints = _build_scope_hints(
        {
            "user_query": "How many different museums or galleries did I visit in the month of February?",
            "assistant_response": "",
            "semantic_summary": "How many different museums or galleries did I visit in the month of February?",
        },
        {"event_cards": [], "numeric_cards": []},
        "2026-04-15T10:45:26",
    )
    assert hints["months"] == ["february"]
    assert "april" not in hints["months"]


def test_numeric_day_month_scope_and_query_variants_cover_broad_recall() -> None:
    hints = _extract_scope_hints_from_text("By the way, I took my niece to the Natural History Museum on 2/8 and she loved the dinosaur exhibit!")
    assert "february" in hints["months"]

    assert _should_use_query_variants_with_full_query(
        "How many days did I spend on camping trips in the United States this year?"
    )
    assert _should_use_query_variants_with_full_query(
        "How many different museums or galleries did I visit in the month of February?"
    )
