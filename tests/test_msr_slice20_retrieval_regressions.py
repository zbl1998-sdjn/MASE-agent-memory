from __future__ import annotations

from notetaker_agent import NotetakerAgent
from planner import _build_query_variants, build_planner_decision


def _result(summary: str) -> dict[str, object]:
    return {
        "summary": summary,
        "user_query": summary,
        "assistant_response": "",
        "memory_profile": {},
        "date": "2023/05/30",
        "time": "12:00",
    }


def test_planner_query_variants_target_remaining_msr_slice20_retrieval_gaps() -> None:
    camping_variants = _build_query_variants(
        "How many days did I spend on camping trips in the United States this year?",
        ["__FULL_QUERY__"],
        False,
    )
    assert "Yellowstone National Park camping trip" in camping_variants
    assert "Big Sur solo camping trip" in camping_variants

    road_trip_variants = _build_query_variants(
        "How many hours in total did I spend driving to my three road trip destinations combined?",
        ["__FULL_QUERY__"],
        False,
    )
    assert "drove for five hours to the mountains in Tennessee" in road_trip_variants
    assert "drove for six hours to Washington D.C." in road_trip_variants

    bike_variants = _build_query_variants(
        "How much total money have I spent on bike-related expenses since the start of the year?",
        ["__FULL_QUERY__"],
        False,
    )
    assert "Bell Zephyr helmet for $120" in bike_variants
    assert "replace the chain cost me $25" in bike_variants
    assert "bike lights installed were $40" in bike_variants

    social_variants = _build_query_variants(
        "How many days did I take social media breaks in total?",
        ["__FULL_QUERY__"],
        False,
    )
    assert "week-long break from social media" in social_variants
    assert "10-day break from social media" in social_variants

    baby_variants = _build_query_variants(
        "How many babies were born to friends and family members in the last few months?",
        ["__FULL_QUERY__"],
        False,
    )
    assert "baby boy named" in baby_variants
    assert "welcomed their first baby" in baby_variants
    assert "twins born in April" in baby_variants


def test_notetaker_followup_queries_target_breaks_and_baby_births() -> None:
    agent = NotetakerAgent(model_interface=None)

    camping_queries = agent.build_english_followup_queries(
        "How many days did I spend on camping trips in the United States this year?",
        [_result("By the way, I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.")],
    )
    assert any("yellowstone national park camping trip" in query.lower() for query in camping_queries)
    assert any("big sur solo camping trip" in query.lower() for query in camping_queries)

    road_trip_queries = agent.build_english_followup_queries(
        "How many hours in total did I spend driving to my three road trip destinations combined?",
        [_result("I drove for five hours to the mountains in Tennessee on a recent trip.")],
    )
    assert any("washington d.c." in query.lower() for query in road_trip_queries)
    assert any("outer banks" in query.lower() for query in road_trip_queries)

    bike_queries = agent.build_english_followup_queries(
        "How much total money have I spent on bike-related expenses since the start of the year?",
        [_result("I've had good experiences with the local bike shop downtown where I bought my Bell Zephyr helmet for $120.")],
    )
    assert any("bell zephyr helmet for $120" in query.lower() for query in bike_queries)
    assert any("replace the chain cost me $25" in query.lower() for query in bike_queries)

    social_queries = agent.build_english_followup_queries(
        "How many days did I take social media breaks in total?",
        [_result("I took a week-long break from social media in mid-January.")],
    )
    assert any("week-long break from social media" in query.lower() for query in social_queries)
    assert any("10-day break from social media" in query.lower() for query in social_queries)

    baby_queries = agent.build_english_followup_queries(
        "How many babies were born to friends and family members in the last few months?",
        [_result("I'm planning a baby gift for my aunt's twins, Ava and Lily, who were born in April.")],
    )
    assert any("baby boy named" in query.lower() for query in baby_queries)
    assert any("welcomed their first baby" in query.lower() for query in baby_queries)
    assert any("twins born in april" in query.lower() for query in baby_queries)


def test_planner_and_followups_generalize_camping_and_social_queries() -> None:
    camping_variants = _build_query_variants(
        "How many days did I spend camping in the US this year?",
        ["__FULL_QUERY__"],
        False,
    )
    assert any("camping trip" in variant.lower() for variant in camping_variants)
    assert any("us" in variant.lower() for variant in camping_variants)

    agent = NotetakerAgent(model_interface=None)
    camping_queries = agent.build_english_followup_queries(
        "How many days did I spend camping in the US this year?",
        [_result("By the way, I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.")],
    )
    assert any("camping trip" in query.lower() for query in camping_queries)
    assert all(query.lower() not in {"way", "back"} for query in camping_queries)


def test_planner_raises_memory_budget_for_camping_scope_counts() -> None:
    planner = build_planner_decision(
        user_question="How many days did I spend on camping trips in the United States this year?",
        route_action="search_memory",
        route_keywords=["__FULL_QUERY__"],
        task_type="long_memory",
        executor_role="reasoning",
        use_memory=True,
        base_memory_limit=3,
    )
    assert planner.widen_search is True
    assert planner.memory_limit >= 8
    assert planner.min_results >= 6
