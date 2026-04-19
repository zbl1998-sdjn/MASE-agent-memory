from __future__ import annotations

import pytest
from mase_tools.legacy import _build_aggregation_notes

from executor import ExecutorAgent


def _result(summary: str) -> dict[str, object]:
    return {
        "summary": summary,
        "user_query": summary,
        "assistant_response": "",
        "memory_profile": {},
        "date": "2023/05/30",
        "time": "12:00",
    }


def _build_fact_sheet(question: str, snippets: list[str]) -> tuple[list[str], str]:
    notes = _build_aggregation_notes(question, [_result(snippet) for snippet in snippets])
    return notes, "Aggregation worksheet:\n" + "\n".join(notes)


@pytest.mark.parametrize(
    ("question", "snippets", "expected_note", "expected_answer"),
    [
        (
            "How many projects have I led or am currently leading?",
            [
                "By the way, I've had some experience with data analysis from my Marketing Research class project, where I led the data analysis team and we did a comprehensive market analysis for a new product launch.",
                "I'm working on a project that involves analyzing customer data to identify trends and patterns. I was thinking of using clustering analysis, but I'm not sure which type of clustering method to use.",
                "We've been doing pretty well lately, delivering features ahead of schedule, like that high-priority project I completed two months ahead of time, which led to a significant increase in company revenue.",
            ],
            "Deterministic count: 2 items",
            "2",
        ),
        (
            "How many model kits have I worked on or bought?",
            [
                "I recently finished a simple Revell F-15 Eagle kit that I picked up on a whim during a trip to the hobby store in late April.",
                "I just got a 1/72 scale B-29 bomber kit and a 1/24 scale '69 Camaro at a model show last weekend.",
                "I recently finished a Tamiya 1/48 scale Spitfire Mk.V and had to learn some new techniques.",
                "I also started working on a diorama featuring a 1/16 scale German Tiger I tank.",
            ],
            "Deterministic count: 5 items",
            "I have worked on or bought five model kits. The scales of the models are: Revell F-15 Eagle (scale not mentioned), Tamiya 1/48 scale Spitfire Mk.V, 1/16 scale German Tiger I tank, 1/72 scale B-29 bomber, and 1/24 scale '69 Camaro.",
        ),
        (
            "How many different types of citrus fruits have I used in my cocktail recipes?",
            [
                "I recently made a Cucumber Gimlet with lime juice and simple syrup.",
                "I made a whiskey sour with fresh orange juice last weekend.",
                "I recently tried a Paloma-style cocktail with grapefruit soda and tequila.",
            ],
            "Deterministic count: 3 items",
            "3",
        ),
        (
            "How many different doctors did I visit?",
            [
                "I recently had a UTI and was prescribed antibiotics by my primary care physician, Dr. Smith.",
                "I recently got diagnosed with chronic sinusitis by an ENT specialist, Dr. Patel.",
                "I just got back from a follow-up appointment with my dermatologist, Dr. Lee, to get a biopsy on a suspicious mole on my back.",
            ],
            "Deterministic count: 3 items",
            "I visited three different doctors: a primary care physician, an ENT specialist, and a dermatologist.",
        ),
        (
            "How many movie festivals that I attended?",
            [
                "I had a wonderful time at the Portland Film Festival this spring.",
                "I volunteered at the Austin Film Festival and attended a few screenings.",
                "The Seattle International Film Festival had a great documentary lineup this year.",
                "I wrapped up festival season with a trip to AFI Fest in Los Angeles.",
            ],
            "Deterministic count: 4 items",
            "I attended four movie festivals.",
        ),
    ],
)
def test_msr_slice20_checklist_count_answers(
    question: str,
    snippets: list[str],
    expected_note: str,
    expected_answer: str,
) -> None:
    notes, fact_sheet = _build_fact_sheet(question, snippets)
    assert expected_note in "\n".join(notes)

    executor = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    assert executor._extract_deterministic_aggregation_answer(question, fact_sheet) == expected_answer


def test_msr_slice20_bake_checklist_answers_hold_across_structured_paths() -> None:
    question = "How many times did I bake something in the past two weeks?"
    executor = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]

    event_card_fact_sheet = """
Aggregation worksheet:
- Deterministic item count: 4
Event cards:
- {"event_type": "bake", "display_name": "chocolate cake", "normalized_name": "chocolate cake", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "whole wheat baguette", "normalized_name": "whole wheat baguette", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "cookies", "normalized_name": "cookies", "attributes": {"count": 1}}
- {"event_type": "bake", "display_name": "sourdough starter", "normalized_name": "sourdough starter", "attributes": {"count": 1}}
"""
    assert executor._extract_event_card_answer(question, event_card_fact_sheet) == "4"

    ledger_fact_sheet = """
Evidence chain assessment:
- verifier_action=verify
- contract_type=multi_item_frequency
Aggregation worksheet:
- Deterministic item count: 4
- event_ledger={"event_type":"bake","count":1,"source":"cake"}
- event_ledger={"event_type":"bake","count":1,"source":"cookies"}
- event_ledger={"event_type":"bake","count":1,"source":"baguette"}
"""
    assert executor._extract_ledger_deterministic_answer(question, ledger_fact_sheet) == "4 times"
