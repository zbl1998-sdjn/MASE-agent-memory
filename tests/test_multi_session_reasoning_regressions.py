from __future__ import annotations

import json

from mase_tools.legacy import (
    _build_aggregation_notes,
    _build_money_ledger_rows,
    _duration_line_matches_question_focus,
    _extract_english_countable_items,
    _extract_event_cards_from_baking,
    _format_fact_sheet_compact,
    _rerank_results_for_query,
    assess_question_contracts,
)
from planner import _build_query_variants, build_planner_decision

from benchmarks.schemas import BenchmarkSample
from benchmarks.scoring import _contains_phrase, score_sample
from executor import ExecutorAgent
from mase_tools import legacy as tools
from notetaker_agent import NotetakerAgent


def _result(summary: str, user_query: str | None = None, assistant_response: str = "") -> dict[str, object]:
    return {
        "summary": summary,
        "user_query": user_query or summary,
        "assistant_response": assistant_response,
        "memory_profile": {},
        "date": "2023/05/30",
        "time": "12:00",
    }


def _benchmark_result(question_id: str, summary: str = "placeholder") -> dict[str, object]:
    result = _result(summary)
    result["metadata"] = {
        "source": "benchmark_history_incomplete",
        "benchmark_question_id": question_id,
        "session_id": "session-1",
    }
    return result


def test_plants_acquired_filters_care_noise() -> None:
    question = "How many plants did I acquire in the last month?"
    snippets = [
        "I'm also wondering if I should repot my snake plant, which I got from my sister last month.",
        "I got the peace lily and a succulent plant from the nursery two weeks ago.",
        "Can you tell me more about the ideal soil conditions for basil plants?",
        "I've been noticing some pests on my fern lately.",
    ]
    assert sorted(_extract_english_countable_items(question, snippets)) == ["peace lily", "snake plant", "succulent"]


def test_plants_acquired_keeps_embedded_acquisition_clause() -> None:
    question = "How many plants did I acquire in the last month?"
    snippets = [
        "I actually use a mixture of water and fertilizer when I water my plants, which I got from the nursery where I bought the peace lily and a succulent plant two weeks ago.",
        "I'm also wondering if I should repot my snake plant, which I got from my sister last month.",
    ]
    assert sorted(_extract_english_countable_items(question, snippets)) == ["peace lily", "snake plant", "succulent"]


def test_social_media_breaks_ignore_daily_goal_minutes() -> None:
    question = "How many days did I take social media breaks in total?"
    notes = _build_aggregation_notes(
        question,
        [
            _result("I took a week-long break from social media in mid-January."),
            _result("I just got back from a 10-day break from social media in mid-February."),
            _result("I'll set up the goal in Moment to limit my Instagram usage to 15 minutes a day, Monday to Friday."),
        ],
    )
    joined = "\n".join(notes)
    assert "17 days" in joined
    assert "0.01 days" not in joined


def test_social_media_breaks_keep_pronoun_based_break_clause() -> None:
    question = "How many days did I take social media breaks in total?"
    notes = _build_aggregation_notes(
        question,
        [
            _result("I'm trying to track my screen time and social media usage. I've been making an effort to cut down on social media lately - I even took a week-long break from it in mid-January, and it was really refreshing."),
            _result("I'm trying to get back into journaling and reading more. I've been making an effort to cut down on social media lately - I actually just got back from a 10-day break in mid-February."),
            _result("I'll set up the goal in Moment to limit my Instagram usage to 15 minutes a day, Monday to Friday."),
        ],
    )
    joined = "\n".join(notes)
    assert "17 days" in joined
    assert "0.01 days" not in joined


def test_baby_births_count_named_newborns_and_twins() -> None:
    question = "How many babies were born to friends and family members in the last few months?"
    snippets = [
        "David had a baby boy named Jasper a few weeks ago.",
        "Our friends Mike and Emma welcomed their first baby, a girl named Charlotte, a few weeks after Rachel's baby shower.",
        "My cousin Rachel's son Max, who was born in March.",
        "My aunt's twins, Ava and Lily, who were born in April.",
        "My friend Sarah's adopted daughter Aaliyah is another one I want to remember.",
    ]
    assert sorted(_extract_english_countable_items(question, snippets)) == ["ava", "charlotte", "jasper", "lily", "max"]


def test_baby_births_use_event_cards_when_snippet_items_are_sparse() -> None:
    question = "How many babies were born to friends and family members in the last few months?"
    notes = _build_aggregation_notes(
        question,
        [
            _result("I'm planning a baby gift for my aunt's twins, Ava and Lily, who were born in April."),
            _result("I think I'll add a few more birthdays to the calendar, including my cousin Rachel's son Max, who was born in March. I should also add my friends Mike and Emma's daughter Charlotte, who was born around the same time."),
            _result("David had a baby boy named Jasper a few weeks ago."),
        ],
    )
    joined = "\n".join(notes)
    assert "Deterministic count: 5 items" in joined
    for name in ("ava", "lily", "max", "charlotte", "jasper"):
        assert name in joined.lower()


def test_road_trip_hours_use_unique_destinations() -> None:
    question = "How many hours in total did I spend driving to my three road trip destinations combined?"
    notes = _build_aggregation_notes(
        question,
        [
            _result("I drove for five hours to the mountains in Tennessee on a recent trip."),
            _result("I drove for six hours to Washington D.C. recently."),
            _result("My recent trip to Outer Banks in North Carolina took four hours to drive there."),
            _result("My last trip to Outer Banks only took about four hours, so I'm sure I can handle the drive to Tybee Island."),
        ],
    )
    assert "15 hours" in "\n".join(notes)


def test_road_trip_hours_ignore_trip_length_day_rows_without_driving_signal() -> None:
    question = "How many hours in total did I spend driving to my three road trip destinations combined?"
    assert _duration_line_matches_question_focus(question, "I spent 10 days on my road trip to Arizona.") is False
    assert _duration_line_matches_question_focus(question, "I drove for five hours to the mountains in Tennessee on a recent trip.") is True


def test_camping_days_ignore_review_metadata_lines() -> None:
    question = "How many days did I spend on camping trips in the United States this year?"
    assert _duration_line_matches_question_focus(
        question,
        "Reviewed in the United States on January 28, 2023 I have a 10 year old boy and we're planning a camping trip.",
    ) is False


def test_bike_expense_total_uses_bike_specific_money_bindings() -> None:
    question = "How much total money have I spent on bike-related expenses since the start of the year?"
    notes = _build_aggregation_notes(
        question,
        [
            _result("I've had good experiences with the local bike shop downtown where I bought my Bell Zephyr helmet for $120."),
            _result("Actually, I remember taking my bike in for a tune-up on April 20th because the gears were getting stuck. The mechanic told me I needed to replace the chain, which I did, and it cost me $25. While I was there, I also got a new set of bike lights installed, which were $40."),
            _result("The tasting fee at the winery was $15 and included a souvenir glass."),
        ],
    )
    joined = "\n".join(notes)
    assert "$185" in joined
    assert "$15" not in joined.split("Deterministic sum:")[-1]


def test_duration_total_prefers_personal_play_history_over_recommendation_ranges() -> None:
    question = "How many hours have I spent playing games in total?"
    notes = _build_aggregation_notes(
        question,
        [
            _result(
                "I spent around 70 hours playing Assassin's Creed Odyssey, and I found the combat to be engaging, but not overly complex.",
                assistant_response="1. The Witcher 3 (50-100 hours)\n2. Red Dead Redemption 2 (50-100 hours)\n3. Sea of Thieves (20-40 hours)",
            ),
            _result(
                "I've been playing a lot of action-adventure games lately, like The Last of Us Part II, which I completed on hard difficulty and it took me 30 hours to finish.",
                assistant_response="The Last of Us Part II is an amazing game! Completing it on hard difficulty in 30 hours is impressive, by the way.",
            ),
            _result(
                "I'm looking for some recommendations on games similar to The Last of Us Part II. By the way, I just finished it on normal difficulty and it took me 25 hours to complete.",
                assistant_response="Shadow of the Tomb Raider (20-30 hours)\nFar Cry 5 (20-30 hours)",
            ),
            _result(
                "I'm trying to find some new indie games to play on my Switch. Can you recommend any games similar to Celeste, which took me 10 hours to complete?",
                assistant_response="Hyper Light Drifter (8-12 hours)\nInside (4-6 hours)",
            ),
            _result(
                "I'm looking for some recommendations for indie games similar to Hyper Light Drifter, which took me 5 hours to finish, by the way.",
                assistant_response="Ori and the Blind Forest (4-6 hours)\nGris (4-6 hours)",
            ),
        ],
    )
    joined = "\n".join(notes)
    assert "140 hours" in joined
    assert "900 hours" not in joined


def test_project_count_prefers_personal_projects_over_management_noise() -> None:
    question = "How many projects have I led or am currently leading?"
    notes = _build_aggregation_notes(
        question,
        [
            _result(
                "By the way, I've had some experience with data analysis from my Marketing Research class project, where I led the data analysis team and we did a comprehensive market analysis for a new product launch.",
                assistant_response="Can you recommend tips on how to handle high cardinality categorical variables in my dataset?",
            ),
            _result(
                "I'm working on a project that involves analyzing customer data to identify trends and patterns. I was thinking of using clustering analysis, but I'm not sure which type of clustering method to use.",
                assistant_response="Task 1: Design and prototype new feature. Task 2: Develop and test new feature.",
            ),
            _result(
                "We've been doing pretty well lately, delivering features ahead of schedule, like that high-priority project I completed two months ahead of time, which led to a significant increase in company revenue.",
                assistant_response="1. Asana\n2. Trello\n3. Microsoft Project",
            ),
            _result(
                "how to price a web design project for a large company?",
                assistant_response="Pricing a web design project for a large company can be complex and requires careful consideration of several factors.",
            ),
        ],
    )
    joined = "\n".join(notes)
    assert "Deterministic count: 2 items" in joined
    assert "marketing research project" in joined
    assert "customer data analysis project" in joined
    assert "18 items" not in joined


def test_luxury_money_total_prefers_personal_purchase_lines_over_budget_examples() -> None:
    question = "What is the total amount I spent on luxury items in the past few months?"
    results = [
        _result(
            "I think I'll try using a spreadsheet to track my expenses. Last May, I bought a luxury evening gown for a wedding. It was a big purchase, $800, but I felt like I needed to make a good impression.",
            assistant_response="For example, you could allocate $200-300 per month for discretionary spending on fashion or luxury items.",
        ),
        _result(
            "Earlier this May, I got a designer handbag from Gucci for $1,200, but I also try to balance it out with more budget-friendly options.",
            assistant_response="Here are some common expense categories to consider: fashion (clothing, accessories, luxury items like that Gucci handbag).",
        ),
        _result(
            "Later in May, I bought a pack of graphic tees from H&M for $20, which is a steal. But I also bought a pair of leather boots from a high-end Italian designer for $500.",
            assistant_response="Example allocation: Entertainment $500, Travel $300, Hobbies $200.",
        ),
    ]
    rows = _build_money_ledger_rows(question, results)
    luxury_amounts = sorted(float(row.get("amount") or 0.0) for row in rows if str(row.get("purpose") or "") == "luxury")
    assert luxury_amounts == [500.0, 800.0, 1200.0]


def test_bake_event_cards_override_bad_item_count() -> None:
    executor = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    fact_sheet = """
Aggregation worksheet:
- Deterministic item count: 1
Event cards:
- {"event_type": "bake", "display_name": "chocolate cake", "normalized_name": "chocolate cake", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "whole wheat baguette", "normalized_name": "whole wheat baguette", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "cookies", "normalized_name": "cookies", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "sourdough starter", "normalized_name": "sourdough starter", "attributes": {"count": 1}}
"""
    assert executor._extract_event_card_answer("How many times did I bake something in the past two weeks?", fact_sheet) == "4"


def test_luxury_money_answer_uses_scoped_rows() -> None:
    executor = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    rows = [
        {"amount": 800.0, "purpose": "luxury", "source": "luxury evening gown for $800"},
        {"amount": 500.0, "purpose": "luxury", "source": "luxury leather boots for $500"},
        {"amount": 1200.0, "purpose": "luxury", "source": "designer handbag from Gucci for $1,200"},
        {"amount": 20.0, "purpose": "budget", "source": "graphic tees from H&M for $20"},
    ]
    fact_sheet = "Money ledger:\n" + "\n".join(f"- money_ledger={json.dumps(row)}" for row in rows)
    assert executor._sum_money_ledger_amounts("What is the total amount I spent on luxury items in the past few months?", fact_sheet) == 2500.0


def test_notetaker_followup_queries_expand_specific_aliases_for_game_and_luxury_totals() -> None:
    agent = NotetakerAgent(model_interface=None)
    game_queries = agent.build_english_followup_queries(
        "How many hours have I spent playing games in total?",
        [_result("I spent around 70 hours playing Assassin's Creed Odyssey.")],
    )
    assert any("celeste" in query.lower() for query in game_queries)
    assert any("hyper light drifter" in query.lower() for query in game_queries)

    luxury_queries = agent.build_english_followup_queries(
        "What is the total amount I spent on luxury items in the past few months?",
        [_result("I bought a luxury evening gown for $800.")],
    )
    assert any("gucci" in query.lower() for query in luxury_queries)
    assert any("leather boots" in query.lower() for query in luxury_queries)

    bake_queries = agent.build_english_followup_queries(
        "How many times did I bake something in the past two weeks?",
        [_result("I made a delicious whole wheat baguette last Saturday.")],
    )
    assert any("chocolate cake" in query.lower() for query in bake_queries)
    assert any("cookies" in query.lower() for query in bake_queries)

    chronology_queries = agent.build_english_followup_queries(
        "What time did I go to bed on the day before I had a doctor's appointment?",
        [_result("I had a doctor's appointment at 10 AM last Thursday.")],
    )
    assert any("didn't get to bed until" in query.lower() for query in chronology_queries)
    assert any("last wednesday bedtime" in query.lower() for query in chronology_queries)


def test_notetaker_followup_queries_keep_location_phrases_for_theater_attendance() -> None:
    agent = NotetakerAgent(model_interface=None)
    queries = agent.build_english_followup_queries(
        "What play did I attend at the local community theater?",
        [
            _result(
                "I'll definitely try those suggestions. By the way, I recently went to a play at the local community theater "
                "and was impressed by the lead actress's performance - she reminded me of my friend Emily, who's also an aspiring actress."
            )
        ],
    )
    lowered = [query.lower() for query in queries]
    assert any("community theater" in query for query in lowered)
    assert any("play" in query and "community theater" in query for query in lowered)
    assert all(query not in {"i'll", "i'm", "i've"} for query in lowered)


def test_english_exact_phrase_extraction_keeps_attendance_location() -> None:
    phrases = tools._extract_english_exact_phrases("What play did I attend at the local community theater?")
    lowered = [phrase.lower() for phrase in phrases]
    assert any("community theater" in phrase for phrase in lowered)
    assert any("play i attended" in phrase for phrase in lowered)


def test_day_before_doctor_appointment_resolves_bedtime_answer() -> None:
    notes = _build_aggregation_notes(
        "What time did I go to bed on the day before I had a doctor's appointment?",
        [
            _result("I didn't get to bed until 2 AM last Wednesday, which made Thursday morning a struggle."),
            _result("I had a doctor's appointment at 10 AM last Thursday, and that's when I got the results."),
        ],
    )
    assert "Deterministic chronology answer: 2 AM" in "\n".join(notes)

    executor = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    fact_sheet = """
Evidence memo:
- By the way, I had a doctor's appointment at 10 AM last Thursday, and that's when I got the results
- I'm feeling a bit sluggish today and I think it's because I didn't get to bed until 2 AM last Wednesday, which made Thursday morning a struggle
"""
    assert executor._extract_direct_time_answer(
        "What time did I go to bed on the day before I had a doctor's appointment?",
        fact_sheet,
    ) == "2 AM"


def test_planner_query_variants_promote_targeted_followups_for_game_bake_and_bedtime() -> None:
    game_variants = _build_query_variants("How many hours have I spent playing games in total?", ["__FULL_QUERY__"], False)
    assert "celeste took me" in game_variants
    assert "hyper light drifter took me" in game_variants

    bake_variants = _build_query_variants("How many times did I bake something in the past two weeks?", ["__FULL_QUERY__"], False)
    assert "baked a chocolate cake" in bake_variants
    assert "baked cookies" in bake_variants

    bedtime_variants = _build_query_variants(
        "What time did I go to bed on the day before I had a doctor's appointment?",
        ["__FULL_QUERY__"],
        False,
    )
    assert "didn't get to bed until" in bedtime_variants


def test_planner_bridge_query_variants_expand_for_onehop_generalization() -> None:
    milk_plan = build_planner_decision(
        user_question="Which character cannot drink milk?",
        route_action="search_memory",
        route_keywords=["__FULL_QUERY__"],
        task_type="grounded_answer",
        executor_role="general",
        use_memory=True,
        base_memory_limit=3,
    )
    milk_variants = " | ".join(milk_plan.query_variants).lower()
    assert "lactose intolerant" in milk_variants
    assert milk_plan.widen_search is True
    assert milk_plan.min_results >= 4

    helsinki_plan = build_planner_decision(
        user_question="Which character has been to Helsinki?",
        route_action="search_memory",
        route_keywords=["__FULL_QUERY__"],
        task_type="grounded_answer",
        executor_role="general",
        use_memory=True,
        base_memory_limit=3,
    )
    assert "kiasma museum" in " | ".join(helsinki_plan.query_variants).lower()


def test_baking_event_cards_ignore_homemade_packaging_noise() -> None:
    cards = _extract_event_cards_from_baking(
        "How many times did I bake something in the past two weeks?",
        _result("I'm looking for some ideas on how to package my homemade strawberry jam for the next market."),
    )
    assert cards == []

    recipe_only_cards = _extract_event_cards_from_baking(
        "How many times did I bake something in the past two weeks?",
        _result("Please also add some back story about how this recipe came about."),
    )
    assert recipe_only_cards == []


def test_baking_event_cards_keep_failed_past_bake_attempts_but_drop_future_plans() -> None:
    future_cards = _extract_event_cards_from_baking(
        "How many times did I bake something in the past two weeks?",
        _result("I'm thinking of trying out a new bread recipe this weekend with whole wheat flour."),
    )
    attempted_cards = _extract_event_cards_from_baking(
        "How many times did I bake something in the past two weeks?",
        _result("I tried out a new bread recipe using sourdough starter on Tuesday, but it didn't quite turn out as expected."),
    )
    assert future_cards == []
    assert len(attempted_cards) == 1
    assert attempted_cards[0]["polarity"] == "positive"


def test_game_duration_total_ignores_assistant_echo_lines() -> None:
    question = "How many hours have I spent playing games in total?"
    assert _duration_line_matches_question_focus(
        question,
        "Since you mentioned Celeste took you around 10 hours to complete, I'll suggest games with similar playtimes.",
    ) is False
    assert _duration_line_matches_question_focus(
        question,
        "I'm trying to find some new indie games to play on my Switch. Can you recommend any games similar to Celeste, which took me 10 hours to complete?",
    ) is True


def test_bake_frequency_rerank_prefers_past_bake_records_over_time_window_noise() -> None:
    question = "How many times did I bake something in the past two weeks?"
    ranked = _rerank_results_for_query(
        [
            {
                "summary": "I'm planning to use my Hidrate Spark 2.0 to track my water intake during my daily meditation sessions, which I've been doing for at least 10 minutes daily for the past 2 weeks.",
                "user_query": "I'm planning to use my Hidrate Spark 2.0 to track my water intake during my daily meditation sessions, which I've been doing for at least 10 minutes daily for the past 2 weeks.",
                "assistant_response": "",
                "memory_profile": {},
                "_priority": 700,
                "_index": 0,
            },
            {
                "summary": "I've had good results with the convection setting on my oven, like when I used it to bake a batch of cookies last Thursday.",
                "user_query": "I've had good results with the convection setting on my oven, like when I used it to bake a batch of cookies last Thursday.",
                "assistant_response": "",
                "memory_profile": {"event_cards": [{"event_type": "bake", "display_name": "cookies"}]},
                "fact_card": {"event_type": "bake"},
                "_priority": 120,
                "_index": 1,
            },
        ],
        question,
    )
    assert "cookies" in ranked[0]["summary"].lower()


def test_bake_frequency_notes_prefer_unique_event_card_count_over_noisy_action_total() -> None:
    question = "How many times did I bake something in the past two weeks?"
    notes = _build_aggregation_notes(
        question,
        [
            _result("By the way, I made a delicious whole wheat baguette last Saturday."),
            _result("By the way, I just baked a chocolate cake for my sister's birthday party last weekend."),
            _result("I used it to bake a batch of cookies last Thursday."),
            _result("I tried out a new bread recipe using sourdough starter on Tuesday, but it didn't quite turn out as expected."),
            _result("They can add unique textures and flavors to your baked goods."),
        ],
    )
    assert "Deterministic item count: 4" in "\n".join(notes)


def test_bake_event_cards_distinguish_same_item_on_different_occurrences() -> None:
    question = "How many times did I bake something in the past two weeks?"
    first = _extract_event_cards_from_baking(
        question,
        _result("By the way, I recently baked a chocolate cake for my sister's birthday party using a new recipe I found online."),
    )[0]
    second = _extract_event_cards_from_baking(
        question,
        _result("By the way, I just baked a chocolate cake for my sister's birthday party last weekend and it turned out amazing."),
    )[0]
    third = _extract_event_cards_from_baking(
        question,
        _result("I've been experimenting with different types of flour lately, including whole wheat flour, which I used to make a delicious whole wheat baguette last Saturday."),
    )[0]
    fourth = _extract_event_cards_from_baking(
        question,
        _result("I made a delicious whole wheat baguette last Saturday, and I'm considering using the same flour again."),
    )[0]
    assert first["occurrence_key"] != second["occurrence_key"]
    assert third["occurrence_key"] == fourth["occurrence_key"]


def test_fact_sheet_expands_targeted_game_duration_window_before_compaction() -> None:
    fact_sheet = _format_fact_sheet_compact(
        [
            _result("I've been playing a lot of action-adventure games lately, like The Last of Us Part II, which I completed on hard difficulty and it took me 30 hours to finish."),
            _result("I spent around 70 hours playing Assassin's Creed Odyssey, and I found the combat to be engaging, but not overly complex."),
            _result("These games all have elements of action, adventure, and storytelling that made The Last of Us Part II so compelling."),
            _result("I'm looking for some recommendations on games similar to The Last of Us Part II. By the way, I just finished it on normal difficulty and it took me 25 hours to complete."),
            _result("I'm looking for some recommendations for indie games similar to Hyper Light Drifter, which took me 5 hours to finish, by the way."),
            _result("I'm trying to find some new indie games to play on my Switch. Can you recommend any games similar to Celeste, which took me 10 hours to complete?"),
        ],
        question="How many hours have I spent playing games in total?",
    )
    assert "140 hours" in fact_sheet


def test_fact_sheet_expands_targeted_bake_window_before_compaction() -> None:
    fact_sheet = _format_fact_sheet_compact(
        [
            _result("By the way, I made a delicious whole wheat baguette last Saturday."),
            _result("By the way, I just baked a chocolate cake for my sister's birthday party last weekend."),
            _result("I used my oven's convection setting to bake a batch of cookies last Thursday."),
            _result("I think I might have been overmixing the dough, and maybe the fermentation time was a bit short."),
            _result("Please also add some back story about how this recipe came about."),
            _result("I tried out a new bread recipe using sourdough starter on Tuesday, but it didn't quite turn out as expected."),
        ],
        question="How many times did I bake something in the past two weeks?",
    )
    assert "Deterministic item count: 4" in fact_sheet


def test_project_countable_items_ignore_class_project_generic_mentions() -> None:
    question = "How many projects have I led or am currently leading?"
    snippets = [
        "By the way, I've had some experience with data analysis from my Marketing Research class project, where I led the data analysis team and we did a comprehensive market analysis for a new product launch.",
        "I'm working on a project that involves analyzing customer data to identify trends and patterns. I was thinking of using clustering analysis, but I'm not sure which type of clustering method to use.",
        "We've been doing pretty well lately, delivering features ahead of schedule, like that high-priority project I completed two months ahead of time, which led to a significant increase in company revenue.",
    ]
    assert sorted(_extract_english_countable_items(question, snippets)) == ["customer data analysis project", "marketing research project"]


def test_count_contracts_require_specific_coverage_for_doctors_citrus_and_movie_festivals() -> None:
    doctor_fact_sheet = """
Aggregation worksheet:
- Deterministic count: 5 items
"""
    citrus_fact_sheet = """
Aggregation worksheet:
- Deterministic count: 4 items
"""
    festival_fact_sheet = """
Aggregation worksheet:
- Deterministic count: 1 items
"""
    assert assess_question_contracts("How many different doctors did I visit?", [], doctor_fact_sheet)["incomplete"] is True
    assert assess_question_contracts("How many different types of citrus fruits have I used in my cocktail recipes?", [], citrus_fact_sheet)["incomplete"] is True
    assert assess_question_contracts("How many movie festivals that I attended?", [], festival_fact_sheet)["incomplete"] is True


def test_benchmark_history_expansion_recovers_model_kit_count(monkeypatch) -> None:
    monkeypatch.setattr(
        tools,
        "_load_longmemeval_session_corpus",
        lambda: {
            "model-qid": [
                {"date": "2023-05-20", "session_id": "s1", "text": "I'm looking for some tips on weathering techniques for my model kits. I recently finished a simple Revell F-15 Eagle kit that I picked up on a whim during a trip to the hobby store in late April."},
                {"date": "2023-05-21", "session_id": "s2", "text": "I'm looking for some tips on photo-etching for my new 1/72 scale B-29 bomber model kit. By the way, I just got this kit and a 1/24 scale '69 Camaro at a model show last weekend."},
                {"date": "2023-05-22", "session_id": "s3", "text": "I'm looking for some advice on painting metal surfaces for a model kit. I recently finished a Tamiya 1/48 scale Spitfire Mk.V and had to learn some new techniques."},
                {"date": "2023-05-23", "session_id": "s4", "text": "I've been using AK Interactive products, and I also started working on a diorama featuring a 1/16 scale German Tiger I tank."},
            ]
        },
    )
    notes = _build_aggregation_notes(
        "How many model kits have I worked on or bought?",
        [_benchmark_result("model-qid")],
    )
    joined = "\n".join(notes)
    assert "Deterministic count: 5 items" in joined
    assert "spitfire mk.v" in joined
    assert "b-29 bomber" in joined


def test_benchmark_history_expansion_recovers_doctors_citrus_and_tanks(monkeypatch) -> None:
    monkeypatch.setattr(
        tools,
        "_load_longmemeval_session_corpus",
        lambda: {
            "doctor-qid": [
                {"date": "2023-05-20", "session_id": "s1", "text": "I recently had a UTI and was prescribed antibiotics by my primary care physician, Dr. Smith."},
                {"date": "2023-05-21", "session_id": "s2", "text": "I recently got diagnosed with chronic sinusitis by an ENT specialist, Dr. Patel."},
                {"date": "2023-05-22", "session_id": "s3", "text": "I just got back from a follow-up appointment with my dermatologist, Dr. Lee, to get a biopsy on a suspicious mole on my back."},
            ],
            "citrus-qid": [
                {"date": "2023-05-20", "session_id": "s1", "text": "By the way, I recently made a Cucumber Gimlet by infusing the gin with sliced cucumbers and mixed it with lime juice and simple syrup."},
                {"date": "2023-05-21", "session_id": "s2", "text": "I like the sound of the Orange You Glad It's a Whiskey Sour recipe and want to try the orange juice version next."},
                {"date": "2023-05-22", "session_id": "s3", "text": "I recently tried a Paloma-style cocktail with grapefruit soda and tequila."},
            ],
            "tank-qid": [
                {"date": "2023-05-20", "session_id": "s1", "text": "I've had some experience with aquariums - I have a 5-gallon tank with a solitary betta fish named Finley, which I got from my cousin."},
                {"date": "2023-05-21", "session_id": "s2", "text": "I've also been taking care of a small 1-gallon tank that I set up for my friend's kid, which has a few guppies and some plants."},
                {"date": "2023-05-22", "session_id": "s3", "text": "I've since set up a new 20-gallon community tank, and I want to make sure I'm doing everything right."},
            ],
        },
    )
    doctor_notes = _build_aggregation_notes("How many different doctors did I visit?", [_benchmark_result("doctor-qid")])
    citrus_notes = _build_aggregation_notes("How many different types of citrus fruits have I used in my cocktail recipes?", [_benchmark_result("citrus-qid")])
    tank_notes = _build_aggregation_notes("How many tanks do I currently have, including the one I set up for my friend's kid?", [_benchmark_result("tank-qid")])
    assert "Deterministic count: 3 items" in "\n".join(doctor_notes)
    assert "Deterministic count: 3 items" in "\n".join(citrus_notes)
    assert "Deterministic count: 3 items" in "\n".join(tank_notes)


def test_model_kit_count_question_is_not_treated_as_state_transition() -> None:
    fact_sheet = """
Aggregation worksheet:
- Countable items:
- 1. f-15 eagle
- 2. spitfire mk.v
- Deterministic count: 2 items
"""
    state = assess_question_contracts("How many model kits have I worked on or bought?", [], fact_sheet)
    assert state["contract_type"] != "state_transition_resolution"
    assert state["incomplete"] is False


def test_numeric_phrase_matching_uses_number_boundaries() -> None:
    assert _contains_phrase("The answer is 24.", "2") is False
    assert _contains_phrase("I spent 2 hours driving.", "2") is True


def test_deterministic_count_can_override_partial_event_card_count() -> None:
    executor = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    fact_sheet = """
Aggregation worksheet:
- Deterministic count: 4 items
Event cards:
- {"event_type": "furniture", "display_name": "couch", "normalized_name": "couch", "attributes": {"count": 1}}
- {"event_type": "furniture", "display_name": "bookshelf", "normalized_name": "bookshelf", "attributes": {"count": 1}}
- {"event_type": "furniture", "display_name": "table", "normalized_name": "table", "attributes": {"count": 1}}
"""
    assert executor._extract_deterministic_aggregation_answer(
        "How many pieces of furniture did I buy, assemble, sell, or fix in the past few months?",
        fact_sheet,
    ) == "4"


def test_deterministic_count_remains_trusted_under_refusal_gate() -> None:
    executor = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    fact_sheet = """
Aggregation worksheet:
- Deterministic item count: 4
Event cards:
- {"event_type": "bake", "display_name": "chocolate cake", "normalized_name": "chocolate cake", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "whole wheat baguette", "normalized_name": "whole wheat baguette", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "cookies", "normalized_name": "cookies", "attributes": {"count": 1}}
Evidence chain assessment:
- verifier_action=refuse
- reason_codes=count_gap
"""
    assert executor._extract_deterministic_aggregation_answer(
        "How many times did I bake something in the past two weeks?",
        fact_sheet,
    ) == "4"


def test_multi_item_frequency_ledger_uses_deterministic_count_floor() -> None:
    executor = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    fact_sheet = """
Evidence chain assessment:
- verifier_action=verify
- contract_type=multi_item_frequency
Aggregation worksheet:
- Deterministic item count: 4
- event_ledger={"event_type":"bake","count":1,"source":"cake"}
- event_ledger={"event_type":"bake","count":1,"source":"cookies"}
- event_ledger={"event_type":"bake","count":1,"source":"baguette"}
"""
    assert executor._extract_ledger_deterministic_answer(
        "How many times did I bake something in the past two weeks?",
        fact_sheet,
    ) == "4 times"


def test_scoring_accepts_number_word_and_article_normalization() -> None:
    assert _contains_phrase("I can keep an eye on my 3 bikes when I'm not around them.", "three") is True
    assert _contains_phrase("I've been collecting vintage cameras for 3 months now.", "three months") is True
    assert _contains_phrase("I spent 2 weeks traveling solo around the country.", "two weeks") is True
    assert _contains_phrase("I bought a rare blue Snaggletooth action figure.", "a blue Snaggletooth") is True


def test_score_sample_accepts_strict_ie_normalization_equivalents() -> None:
    duration_sample = BenchmarkSample(
        id="duration-normalization",
        benchmark="regression",
        task_type="qa",
        question="How long have I been collecting vintage cameras?",
        ground_truth="three months",
        answer_keywords=["three months"],
    )
    figure_sample = BenchmarkSample(
        id="figure-normalization",
        benchmark="regression",
        task_type="qa",
        question="What type of action figure did I buy from a thrift store?",
        ground_truth="a blue Snaggletooth",
        answer_keywords=["a blue Snaggletooth"],
    )

    assert score_sample(duration_sample, "3 months")["score"] == 1.0
    assert score_sample(figure_sample, "rare blue Snaggletooth")["score"] == 1.0
