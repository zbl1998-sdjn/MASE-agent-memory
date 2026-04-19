from __future__ import annotations

from mase_tools.legacy import _build_aggregation_notes, _build_duration_ledger_rows, _location_scope_matches_text


def _result(summary: str, *, user_query: str | None = None) -> dict[str, object]:
    text = user_query or summary
    return {
        "summary": summary,
        "user_query": text,
        "assistant_response": "",
        "memory_profile": {},
        "date": "2023/05/30",
        "time": "12:00",
    }


def test_united_states_scope_rejects_review_noise_and_future_recommendations() -> None:
    assert _location_scope_matches_text(
        "united states",
        "Reviewed in the United States on January 28, 2023. Verified Purchase.",
        ["united states"],
    ) is False
    assert _location_scope_matches_text(
        "united states",
        "I'm also interested in visiting some of the nearby national parks. Can you recommend some day trips or shorter trips to national parks near Moab?",
        ["moab"],
    ) is False
    assert _location_scope_matches_text(
        "united states",
        "I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
        ["yellowstone national park"],
    ) is True
    assert _location_scope_matches_text(
        "united states",
        "I just got back from a 3-day solo camping trip to Big Sur in early April.",
        ["big sur"],
    ) is True


def test_camping_days_ignore_scope_leakage_and_future_noise() -> None:
    question = "How many days did I spend on camping trips in the United States this year?"
    notes = _build_aggregation_notes(
        question,
        [
            _result(
                "for this product: Amazon Essentials Boys and Toddlers' Fleece Pullover Hoodie Sweatshirts.",
                user_query="5.0 out of 5 stars Reviewed in the United States on January 28, 2023. Verified Purchase.",
            ),
            _result("I'm also interested in visiting some of the nearby national parks. Can you recommend some day trips or shorter trips to national parks near Moab?"),
            _result("By the way, I just got back from an amazing 5-day camping trip to Yellowstone National Park last month, and I'm still buzzing from the experience."),
            _result("I just got back from a 3-day solo camping trip to Big Sur in early April."),
            _result("I'm planning a 10-day trek in New Zealand in November and I'll be hiking on varying terrain."),
        ],
    )
    joined = "\n".join(notes)
    assert "Deterministic sum: 5 days + 3 days = 8 days" in joined
    assert "2-4 days" not in joined


def test_road_trip_duration_ignores_itinerary_contamination_under_strict_scope() -> None:
    question = "How many hours in total did I spend driving to my three road trip destinations combined?"
    notes = _build_aggregation_notes(
        question,
        [
            _result("I drove for five hours to the mountains in Tennessee on a recent trip."),
            _result("I drove for six hours to Washington D.C. recently."),
            _result("My recent trip to Outer Banks in North Carolina took four hours to drive there."),
            _result("My last trip to Outer Banks only took about four hours, so I'm sure I can handle the drive to Tybee Island."),
            _result("I think I'll go with Option 1: Return to Yellowstone and explore the west side of the park, then head back to your hometown (approx. 4 hours)."),
            _result("Option 2: Utah's Mighty Five National Parks starts from your hometown and heads west to Moab, Utah (approx. 18 hours)."),
        ],
    )
    joined = "\n".join(notes)
    assert "Deterministic sum: 5 hours + 6 hours + 4 hours = 15 hours" in joined
    assert "18 hours" not in joined.split("Deterministic sum:")[-1]


def test_benchmark_hydrated_duration_carries_scope_into_followup_sentence() -> None:
    question = "How many days did I spend in total traveling in Hawaii and in New York City?"
    rows = _build_duration_ledger_rows(
        question,
        [
            {
                "summary": "I just got back from an amazing island-hopping trip to Hawaii with my family.",
                "user_query": "I just got back from an amazing island-hopping trip to Hawaii with my family.",
                "assistant_response": "",
                "memory_profile": {},
                "date": "2023/05/30",
                "time": "12:00",
                "metadata": {
                    "source": "benchmark_history_incomplete",
                    "benchmark_question_id": "edced276",
                    "session_id": "answer_60e8941a_1",
                },
            }
        ],
    )
    assert any(float(row.get("days") or 0.0) == 10.0 for row in rows)
    assert any("hawaii" in " ".join(row.get("location") or []).lower() for row in rows)
