from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase.fact_sheet import build_long_context_fact_sheet, build_long_memory_full_fact_sheet
from mase.engine import MASESystem
from mase.model_interface import ModelInterface
from mase.mode_selector import (
    generalizer_mode_for_question,
    local_only_models_enabled,
    long_context_search_limit,
    multipass_allowed_for_task,
    select_executor_mode,
    verify_mode_for_question,
)


class _DummyNotetaker:
    def _extract_terms(self, keywords, full_query=None, query_variants=None):
        del keywords, query_variants
        return str(full_query or "").split()


def test_long_context_fact_sheet_adds_candidate_table_for_english_name_disambiguation() -> None:
    question = "What is the name of the scientist widely acclaimed as the foundational figure of modern physics?"
    results = [
        {
            "content": (
                "David Beckham was an Italian astronomer, physicist, mathematician, and philosopher, "
                "regarded as one of the pioneers of modern astronomy."
            ),
            "score": 36,
        },
        {
            "content": (
                "Due to his contributions to theoretical physics, Ludwig Beethoven received numerous honors, "
                "including the Nobel Prize in Physics in 1921."
            ),
            "score": 26,
        },
    ]

    fact_sheet = build_long_context_fact_sheet(
        user_question=question,
        search_results=results,
        notetaker=_DummyNotetaker(),
        multidoc=False,
        long_memory=False,
    )

    assert "Candidate table:" in fact_sheet
    assert "name=David Beckham" in fact_sheet
    assert "name=Ludwig Beethoven" in fact_sheet


def test_long_context_fact_sheet_adds_candidate_table_for_chinese_name_disambiguation() -> None:
    question = "被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？"
    results = [
        {
            "content": (
                "基准历史：庚子年间，贝多芬，乃一德裔美籍学士，研究于物理理学。"
                "彼探求相对论、量子力学，实乃现代物理学之奠基者。"
            ),
            "score": 40,
        },
        {
            "content": (
                "贝克汉姆乃为意大利一代名天文、物理、数学、哲学俱备之士，"
                "为今日现代天文之奠基者。"
            ),
            "score": 23,
        },
    ]

    fact_sheet = build_long_context_fact_sheet(
        user_question=question,
        search_results=results,
        notetaker=_DummyNotetaker(),
        multidoc=False,
        long_memory=False,
    )

    assert "候选裁决表" in fact_sheet
    assert "name=贝多芬" in fact_sheet
    assert "name=贝克汉姆" in fact_sheet


def test_candidate_table_can_recover_name_before_matched_phrase() -> None:
    question = "What is the name of the scientist widely acclaimed as the foundational figure of modern physics?"
    results = [
        {
            "content": (
                "His contributions include significant advancements in relativity and quantum mechanics. "
                "Due to his contributions to theoretical physics, Ludwig Beethoven received numerous honors. "
                "He is widely regarded as one of the founders of modern physics."
            ),
            "score": 35,
        },
        {
            "content": (
                "David Beckham made significant contributions to physics, particularly in kinematics and free-fall motion."
            ),
            "score": 26,
        },
    ]

    fact_sheet = build_long_context_fact_sheet(
        user_question=question,
        search_results=results,
        notetaker=_DummyNotetaker(),
        multidoc=False,
        long_memory=False,
    )

    assert "Candidate table:" in fact_sheet
    assert "name=Ludwig Beethoven" in fact_sheet


def test_long_memory_full_fact_sheet_keeps_same_session_halo_for_priority_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    all_rows = [
        {"id": 1, "content": "User: unrelated old note", "metadata": '{"session_id":"s1","timestamp":"2023/04/01"}'},
        {"id": 2, "content": "User: I just got back from Yosemite today.", "metadata": '{"session_id":"s2","timestamp":"2023/04/20"}'},
        {"id": 3, "content": "User: We also went on a road trip to Big Sur and Monterey.", "metadata": '{"session_id":"s2","timestamp":"2023/04/20"}'},
        {"id": 4, "content": "Assistant: Sounds like a great trip.", "metadata": '{"session_id":"s2","timestamp":"2023/04/20"}'},
        {"id": 5, "content": "User: recent unrelated tail note", "metadata": '{"session_id":"s3","timestamp":"2023/05/01"}'},
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="What is the order of the three trips I took in the past three months, from earliest to latest?",
        all_rows=all_rows,
        priority_ids={2},
        char_budget=5000,
        max_priority=10,
    )

    assert "Yosemite" in fact_sheet
    assert "Big Sur and Monterey" in fact_sheet


def test_long_memory_full_fact_sheet_adds_question_focused_evidence_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "multi-session")

    all_rows = [
        {
            "id": 1,
            "content": "User: I need to pick up my dry cleaning for the navy blue blazer.",
            "metadata": '{"session_id":"s1","timestamp":"2023/02/01"}',
        },
        {
            "id": 2,
            "content": "User: I need to return some boots to Zara, but I exchanged them and still need to pick them up.",
            "metadata": '{"session_id":"s2","timestamp":"2023/02/05"}',
        },
        {
            "id": 3,
            "content": "User: Recent unrelated note about watering plants.",
            "metadata": '{"session_id":"s3","timestamp":"2023/05/01"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="How many items of clothing do I need to pick up or return from a store?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=5000,
    )

    assert "Question-focused evidence scan" in fact_sheet
    assert "Pickup/return rule" in fact_sheet
    assert "dry cleaning" in fact_sheet
    assert "boots to Zara" in fact_sheet
    assert "matches=" in fact_sheet


def test_long_memory_evidence_scan_expands_domain_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "multi-session")

    all_rows = [
        {
            "id": 1,
            "content": "User: I viewed a 1-bedroom condo on February 10th, but the noise from the highway was a deal-breaker.",
            "metadata": '{"session_id":"s1","timestamp":"2023/02/10"}',
        },
        {
            "id": 2,
            "content": "User: I saw a bungalow in Oakwood, but the kitchen needed serious renovation work.",
            "metadata": '{"session_id":"s2","timestamp":"2023/01/22"}',
        },
        {
            "id": 3,
            "content": "User: My offer on the 2-bedroom condo was rejected because there was a higher bid.",
            "metadata": '{"session_id":"s3","timestamp":"2023/02/17"}',
        },
        {
            "id": 4,
            "content": "User: That property in Cedar Creek did not fit my budget.",
            "metadata": '{"session_id":"s4","timestamp":"2023/02/01"}',
        },
        {
            "id": 5,
            "content": "User: I made an offer on the townhouse in the Brookside neighborhood.",
            "metadata": '{"session_id":"s5","timestamp":"2023/02/20"}',
        },
        {
            "id": 6,
            "content": "User: My weekends have been all about Uber Eats lately.",
            "metadata": '{"session_id":"s6","timestamp":"2023/05/12"}',
        },
    ]

    property_sheet = build_long_memory_full_fact_sheet(
        user_question="How many properties did I view before making an offer on the townhouse in the Brookside neighborhood?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=5000,
    )
    delivery_sheet = build_long_memory_full_fact_sheet(
        user_question="How many different types of food delivery services have I used recently?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=5000,
    )

    assert "Before-offer scope rule" in property_sheet
    assert "Before-offer candidate ledger" in property_sheet
    assert "Deterministic candidate count: 4" in property_sheet
    assert "1-bedroom condo" in property_sheet
    assert "bungalow in Oakwood" in property_sheet
    assert "2-bedroom condo" in property_sheet
    assert "Cedar Creek" in property_sheet
    ledger_lines = property_sheet.split("Before-offer candidate ledger", 1)[1].split("Deterministic candidate count", 1)[0]
    candidate_lines = "\n".join(line for line in ledger_lines.splitlines() if line.startswith("- "))
    assert "Brookside" not in candidate_lines
    assert "Delivery-service rule" in delivery_sheet
    assert "Uber Eats" in delivery_sheet


def test_long_memory_evidence_scan_adds_operational_ledgers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "multi-session")

    all_rows = [
        {
            "id": 1,
            "content": "User: I need to return some boots to Zara because I exchanged them for a larger size and still need to pick up the new pair.",
            "metadata": '{"session_id":"s1","timestamp":"2023/02/05"}',
        },
        {
            "id": 2,
            "content": "User: I still need to pick up my dry cleaning for the navy blue blazer.",
            "metadata": '{"session_id":"s2","timestamp":"2023/02/06"}',
        },
        {
            "id": 3,
            "content": "User: I just canceled my Forbes magazine subscription, but I have been loving The New Yorker.",
            "metadata": '{"session_id":"s3","timestamp":"2023/03/01"}',
        },
        {
            "id": 4,
            "content": "User: I'm also getting Architectural Digest, which I love for home decor inspiration.",
            "metadata": '{"session_id":"s4","timestamp":"2023/03/02"}',
        },
        {
            "id": 5,
            "content": "User: My flea market find is actually worth triple what I paid for it.",
            "metadata": '{"session_id":"s5","timestamp":"2023/05/30"}',
        },
        {
            "id": 6,
            "content": "User: The sunset hidden gems in Seoul were beautiful but unrelated to my art collection.",
            "metadata": '{"session_id":"s6","timestamp":"2023/05/20"}',
        },
        {
            "id": 7,
            "content": "User: I came back from Michael's engagement party today.",
            "metadata": '{"session_id":"s7","timestamp":"2023/05/06"}',
        },
        {
            "id": 8,
            "content": "User: I walked down the aisle as a bridesmaid at my cousin's wedding today.",
            "metadata": '{"session_id":"s8","timestamp":"2023/06/15"}',
        },
    ]

    clothing_sheet = build_long_memory_full_fact_sheet(
        user_question="How many items of clothing do I need to pick up or return from a store?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )
    subscription_sheet = build_long_memory_full_fact_sheet(
        user_question="How many magazine subscriptions do I currently have?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )
    value_sheet = build_long_memory_full_fact_sheet(
        user_question="How much is the painting worth in terms of the amount I paid for it?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )
    temporal_sheet = build_long_memory_full_fact_sheet(
        user_question="Which event happened first, my cousin's wedding or Michael's engagement party?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Pickup/return obligation ledger" in clothing_sheet
    assert "Deterministic obligation count: 3" in clothing_sheet
    assert "Current magazine-subscription ledger" in subscription_sheet
    assert "Forbes: inactive canceled" in subscription_sheet
    assert "Deterministic active subscription count: 2" in subscription_sheet
    assert "Value relation ledger" in value_sheet
    assert "worth triple what was paid" in value_sheet
    assert "Deterministic value answer" in value_sheet
    value_scan = value_sheet.split("[1]", 1)[0]
    assert "sunset hidden gems" not in value_scan
    assert "Temporal event ledger" in temporal_sheet
    assert temporal_sheet.index("Michael's engagement party") < temporal_sheet.index("cousin's wedding")


def test_long_memory_temporal_ledger_adds_delta_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    all_rows = [
        {
            "id": 1,
            "content": "User: I repotted the previous spider plant today.",
            "metadata": '{"session_id":"s1","timestamp":"2023/03/08 (Wed) 10:00"}',
        },
        {
            "id": 2,
            "content": "User: I gave my neighbor Mrs. Johnson a few cuttings from my spider plant today.",
            "metadata": '{"session_id":"s2","timestamp":"2023/03/22 (Wed) 11:00"}',
        },
        {
            "id": 3,
            "content": "User: I finished an unrelated article about plants.",
            "metadata": '{"session_id":"s3","timestamp":"2023/03/25 (Sat) 11:00"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="How many days passed between the day I repotted the previous spider plant and the day I gave my neighbor, Mrs. Johnson, a few cuttings from my spider plant?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal event ledger" in fact_sheet
    assert "repotted the previous spider plant" in fact_sheet
    assert "gave my neighbor Mrs. Johnson" in fact_sheet
    assert "Deterministic temporal answer: 14 calendar days" in fact_sheet
    assert "delta_from_previous_candidate: 14 calendar days" in fact_sheet


def test_long_memory_temporal_answer_ledger_uses_explicit_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    all_rows = [
        {
            "id": 1,
            "content": 'User: I attended the workshop on "Effective Communication in the Workplace" on January 10th.',
            "metadata": '{"session_id":"s1","timestamp":"2023/01/13 (Fri) 01:02"}',
        },
        {
            "id": 2,
            "content": "User: I am preparing for my upcoming team meeting on January 17th.",
            "metadata": '{"session_id":"s2","timestamp":"2023/01/13 (Fri) 13:59"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="How many days before the team meeting I was preparing for did I attend the workshop on 'Effective Communication in the Workplace'?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (deterministic date math)" in fact_sheet
    assert "workshop event: 2023/01/10" in fact_sheet
    assert "team-meeting event: 2023/01/17" in fact_sheet
    assert "Deterministic temporal answer: 7 calendar days" in fact_sheet


def test_long_memory_temporal_answer_ledger_extracts_person_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    all_rows = [
        {
            "id": 1,
            "content": "User: I just started taking ukulele lessons with my friend Rachel today.",
            "metadata": '{"session_id":"s1","timestamp":"2023/02/01 (Wed) 14:38"}',
        },
        {
            "id": 2,
            "content": "User: Rachel Taylor gave a public interview about city planning.",
            "metadata": '{"session_id":"s2","timestamp":"2023/02/01 (Wed) 18:00"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="What did I do with Rachel on the Wednesday two months ago?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (target person/action)" in fact_sheet
    assert "started taking ukulele lessons with my friend Rachel" in fact_sheet
    assert "Rachel Taylor gave a public interview" not in fact_sheet.split("Temporal event ledger", 1)[0]


def test_long_memory_temporal_answer_ledger_computes_membership_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    all_rows = [
        {
            "id": 1,
            "content": 'User: I recently joined a Facebook group called "Book Lovers Unite" three weeks ago.',
            "metadata": '{"session_id":"s1","timestamp":"2023/05/28 (Sun) 21:28"}',
        },
        {
            "id": 2,
            "content": "User: I attended a meetup organized by Book Lovers Unite last week.",
            "metadata": '{"session_id":"s2","timestamp":"2023/05/28 (Sun) 03:59"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="How long had I been a member of 'Book Lovers Unite' when I attended the meetup?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (membership duration)" in fact_sheet
    assert "joined Book Lovers Unite: 2023/05/07" in fact_sheet
    assert "attended meetup: 2023/05/21" in fact_sheet
    assert "Deterministic temporal answer: 2 weeks." in fact_sheet


def test_long_memory_temporal_answer_ledger_extracts_event_companion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    all_rows = [
        {
            "id": 1,
            "content": "User: I got back from a music festival in Brooklyn with a group of friends.",
            "metadata": '{"session_id":"s0","timestamp":"2023/04/01 (Sat) 15:57"}',
        },
        {
            "id": 2,
            "content": "User: I went to see Queen with Adam Lambert at Prudential Center with my parents last Saturday.",
            "metadata": '{"session_id":"s1","timestamp":"2023/04/15 (Sat) 20:00"}',
        },
        {
            "id": 3,
            "content": "User: I listened to jazz alone at home yesterday.",
            "metadata": '{"session_id":"s2","timestamp":"2023/04/16 (Sun) 20:00"}',
        },
        {
            "id": 4,
            "content": "User: I saw a festival with a strong indie rock lineup.",
            "metadata": '{"session_id":"s3","timestamp":"2023/04/15 (Sat) 21:00"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="Who did I go with to the music event last Saturday?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (event companion)" in fact_sheet
    assert "Deterministic temporal answer: my parents." in fact_sheet


def test_long_memory_temporal_answer_ledger_orders_relative_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    all_rows = [
        {
            "id": 1,
            "content": "User: I did a great job with the goat's hoove trimming two weeks ago.",
            "metadata": '{"session_id":"s1","timestamp":"2023/05/25 (Thu) 07:52"}',
        },
        {
            "id": 2,
            "content": "User: I just fixed that broken fence on the east side of my property three weeks ago.",
            "metadata": '{"session_id":"s2","timestamp":"2023/05/25 (Thu) 14:25"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="Which task did I complete first, fixing the fence or trimming the goats' hooves?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (task order)" in fact_sheet
    assert fact_sheet.index("Fixing the fence: 2023/05/04") < fact_sheet.index("Trimming the goats' hooves: 2023/05/11")
    assert "Deterministic temporal answer: Fixing the fence." in fact_sheet


def test_long_memory_temporal_answer_ledger_answers_negative_museum_companion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    all_rows = [
        {
            "id": 1,
            "content": "User: I went to a behind-the-scenes tour of the Science Museum with a friend who's a chemistry professor.",
            "metadata": '{"session_id":"s1","timestamp":"2022/10/22 (Sat) 23:02"}',
        },
        {
            "id": 2,
            "content": "User: I attended a guided tour at the Natural History Museum yesterday with my dad.",
            "metadata": '{"session_id":"s2","timestamp":"2023/02/18 (Sat) 00:56"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="I mentioned visiting a museum two months ago. Did I visit with a friend or not?",
        all_rows=all_rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (relative companion)" in fact_sheet
    assert "selected museum visit" in fact_sheet
    assert "with my dad" in fact_sheet
    assert "Deterministic temporal answer: No, you did not visit with a friend." in fact_sheet


def test_long_memory_temporal_answer_ledger_handles_days_ago(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2022/04/04 (Mon) 21:03")

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="How many days ago did I attend a networking event?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I just got back from a networking event that ran from 6 PM to 8 PM today.",
                "metadata": '{"session_id":"s1","timestamp":"2022/03/09 (Wed) 12:08"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (days ago)" in fact_sheet
    assert "Deterministic temporal answer: 26 calendar days ago" in fact_sheet


def test_long_memory_temporal_answer_ledger_handles_event_locations_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    art_sheet = build_long_memory_full_fact_sheet(
        user_question="I mentioned that I participated in an art-related event two weeks ago. Where was that event held at?",
        all_rows=[
            {
                "id": 1,
                "content": 'User: I attended the "Ancient Civilizations" exhibit at the Metropolitan Museum of Art today.',
                "metadata": '{"session_id":"s1","timestamp":"2023/01/15 (Sun) 13:43"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    social_sheet = build_long_memory_full_fact_sheet(
        user_question="Which event happened first, my participation in the #PlankChallenge or my post about vegan chili recipe?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I shared a recipe for vegan chili using #FoodieAdventures yesterday.",
                "metadata": '{"session_id":"s1","timestamp":"2023/03/10 (Fri) 11:15"}',
            },
            {
                "id": 2,
                "content": "User: I participated in a social media challenge called #PlankChallenge today.",
                "metadata": '{"session_id":"s2","timestamp":"2023/03/15 (Wed) 14:28"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    religious_sheet = build_long_memory_full_fact_sheet(
        user_question="Where did I attend the religious activity last week?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I got to attend the Maundy Thursday service at the Episcopal Church.",
                "metadata": '{"session_id":"s1","timestamp":"2023/04/06 (Thu) 05:36"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Deterministic temporal answer: The Metropolitan Museum of Art." in art_sheet
    assert "Deterministic temporal answer: vegan chili recipe post happened first." in social_sheet
    assert "Deterministic temporal answer: the Episcopal Church." in religious_sheet


def test_long_memory_temporal_answer_ledger_handles_relative_artist_and_life_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    artist_sheet = build_long_memory_full_fact_sheet(
        user_question="What is the artist that I started to listen to last Friday?",
        all_rows=[
            {
                "id": 1,
                "content": (
                    "User: I recently discovered a bluegrass band that features a banjo player "
                    "and started enjoying their music today."
                ),
                "metadata": '{"session_id":"s1","timestamp":"2023/03/31 (Fri) 14:13"}',
            },
            {
                "id": 2,
                "content": "User: I also listen to Jinsang while studying.",
                "metadata": '{"session_id":"s2","timestamp":"2023/03/18 (Sat) 16:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    life_event_sheet = build_long_memory_full_fact_sheet(
        user_question="What was the the life event of one of my relatives that I participated in a week ago?",
        all_rows=[
            {
                "id": 1,
                "content": (
                    "User: I recently walked down the aisle as a bridesmaid at my cousin's wedding, "
                    "and it got me thinking about my own wedding."
                ),
                "metadata": '{"session_id":"s1","timestamp":"2023/06/15 (Thu) 10:02"}',
            },
            {
                "id": 2,
                "content": "User: My cousin Rachel had a baby shower back in February.",
                "metadata": '{"session_id":"s2","timestamp":"2023/06/15 (Thu) 10:05"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (relative artist)" in artist_sheet
    assert "Deterministic temporal answer: a bluegrass band that features a banjo player." in artist_sheet
    assert "Temporal answer ledger (relative life event)" in life_event_sheet
    assert "Deterministic temporal answer: my cousin's wedding." in life_event_sheet


def test_long_memory_temporal_answer_ledger_handles_sports_event_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="What is the order of the sports events I watched in January?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I just went to a NBA game at the Staples Center today and watched the Lakers.",
                "metadata": '{"session_id":"s1","timestamp":"2023/01/05 (Thu) 16:31"}',
            },
            {
                "id": 2,
                "content": "User: I watched the College Football National Championship game with my family yesterday.",
                "metadata": '{"session_id":"s2","timestamp":"2023/01/15 (Sun) 00:46"}',
            },
            {
                "id": 3,
                "content": (
                    "User: I watched the Kansas City Chiefs defeat the Buffalo Bills "
                    "in the Divisional Round of the NFL playoffs last weekend."
                ),
                "metadata": '{"session_id":"s3","timestamp":"2023/01/22 (Sun) 12:52"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Temporal answer ledger (sports event order)" in fact_sheet
    assert "NBA game at the Staples Center: 2023/01/05" in fact_sheet
    assert "College Football National Championship game: 2023/01/14" in fact_sheet
    assert "NFL playoffs" in fact_sheet
    assert "First, I attended a NBA game at the Staples Center" in fact_sheet


def test_long_memory_temporal_answer_ledger_handles_relative_holdout_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/04/18 (Tue) 03:31")

    charity_sheet = build_long_memory_full_fact_sheet(
        user_question="How many months have passed since I participated in two charity events in a row, on consecutive days?",
        all_rows=[
            {
                "id": 1,
                "content": 'User: I just got back from the "24-Hour Bike Ride" charity event today.',
                "metadata": '{"session_id":"s1","timestamp":"2023/02/14 (Tue) 09:06"}',
            },
            {
                "id": 2,
                "content": 'User: I volunteered at the "Books for Kids" charity book drive event today.',
                "metadata": '{"session_id":"s2","timestamp":"2023/02/15 (Wed) 19:39"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    exchange_sheet = build_long_memory_full_fact_sheet(
        user_question="How many weeks have I been accepted into the exchange program when I started attending the pre-departure orientation sessions?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I got accepted on March 20th into the exchange program.",
                "metadata": '{"session_id":"s1","timestamp":"2023/04/19 (Wed) 03:31"}',
            },
            {
                "id": 2,
                "content": "User: I've been attending pre-departure orientation sessions every Friday since 3/27.",
                "metadata": '{"session_id":"s2","timestamp":"2023/04/19 (Wed) 02:37"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    appliance_sheet = build_long_memory_full_fact_sheet(
        user_question="What kitchen appliance did I buy 10 days ago?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I just got a smoker today and I'm excited to experiment with different woods.",
                "metadata": '{"session_id":"s1","timestamp":"2023/03/15 (Wed) 11:56"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    book_sheet = build_long_memory_full_fact_sheet(
        user_question="Which book did I finish a week ago?",
        all_rows=[
            {
                "id": 1,
                "content": 'User: I just finished a historical fiction novel, "The Nightingale" by Kristin Hannah, today.',
                "metadata": '{"session_id":"s1","timestamp":"2023/01/31 (Tue) 02:37"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Deterministic temporal answer: 2." in charity_sheet
    assert "Deterministic temporal answer: one week." in exchange_sheet
    assert "Deterministic temporal answer: a smoker." in appliance_sheet
    assert "Deterministic temporal answer: 'The Nightingale' by Kristin Hannah." in book_sheet


def test_long_memory_temporal_answer_ledger_handles_relative_source_and_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    flu_sheet = build_long_memory_full_fact_sheet(
        user_question="How many weeks had passed since I recovered from the flu when I went on my 10th jog outdoors?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I'm feeling much better now that I finally recovered from the flu today.",
                "metadata": '{"session_id":"s1","timestamp":"2023/01/19 (Thu) 10:47"}',
            },
            {
                "id": 2,
                "content": "User: I went on my 10th jog outdoors today, and it feels great to be back in shape.",
                "metadata": '{"session_id":"s2","timestamp":"2023/04/10 (Mon) 20:58"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    gift_sheet = build_long_memory_full_fact_sheet(
        user_question=(
            "How many days had passed between the day I bought a gift for my brother's graduation ceremony "
            "and the day I bought a birthday gift for my best friend?"
        ),
        all_rows=[
            {
                "id": 1,
                "content": "User: I recently got a wireless headphone for my brother as a graduation gift on the 3/8.",
                "metadata": '{"session_id":"s1","timestamp":"2023/03/29 (Wed) 21:27"}',
            },
            {
                "id": 2,
                "content": "User: I recently got a silver necklace with a tiny pendant for my best friend's 30th birthday on the 15th of March.",
                "metadata": '{"session_id":"s2","timestamp":"2023/03/29 (Wed) 21:48"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    airline_sheet = build_long_memory_full_fact_sheet(
        user_question="What was the airline that I flied with on Valentine's day?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I'm still recovering from my American Airlines flight from LAX to JFK.",
                "metadata": '{"session_id":"s1","timestamp":"2023/02/14 (Tue) 20:47"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/03/09 (Thu) 15:47")
    source_sheet = build_long_memory_full_fact_sheet(
        user_question="I received a piece of jewelry last Saturday from whom?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I also got a stunning crystal chandelier from my aunt today.",
                "metadata": '{"session_id":"s1","timestamp":"2023/03/04 (Sat) 16:45"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Deterministic temporal answer: 15." in flu_sheet
    assert "Deterministic temporal answer: 7 days. 8 days (including the last day) is also acceptable." in gift_sheet
    assert "Deterministic temporal answer: American Airlines." in airline_sheet
    assert "Deterministic temporal answer: my aunt." in source_sheet


def test_long_memory_temporal_answer_ledger_handles_tail_holdout_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    sports_sheet = build_long_memory_full_fact_sheet(
        user_question="What is the order of the three sports events I participated in during the past month, from earliest to latest?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I just completed the Spring Sprint Triathlon today.",
                "metadata": '{"session_id":"s1","timestamp":"2023/06/02 (Fri) 15:29"}',
            },
            {
                "id": 2,
                "content": "User: I just finished a personal best time at the Midsummer 5K Run.",
                "metadata": '{"session_id":"s2","timestamp":"2023/06/10 (Sat) 15:00"}',
            },
            {
                "id": 3,
                "content": "User: I participate in the company's annual charity soccer tournament today.",
                "metadata": '{"session_id":"s3","timestamp":"2023/06/17 (Sat) 11:09"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    comedy_sheet = build_long_memory_full_fact_sheet(
        user_question=(
            "How long had I been watching stand-up comedy specials regularly when I attended the "
            "open mic night at the local comedy club?"
        ),
        all_rows=[
            {
                "id": 1,
                "content": "User: I've been really into stand-up lately - it started about 3 months ago and I've been watching stand-ups regularly ever since.",
                "metadata": '{"session_id":"s1","timestamp":"2023/05/20 (Sat) 12:45"}',
            },
            {
                "id": 2,
                "content": "User: Last month, I finally worked up the courage to attend an open mic night at a local comedy club.",
                "metadata": '{"session_id":"s2","timestamp":"2023/05/20 (Sat) 09:41"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    gift_sheet = build_long_memory_full_fact_sheet(
        user_question="Which gift did I buy first, the necklace for my sister or the photo album for my mom?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I already got her a beautiful necklace from Tiffany's last weekend.",
                "metadata": '{"session_id":"s1","timestamp":"2023/05/30 (Tue) 09:00"}',
            },
            {
                "id": 2,
                "content": "User: I ordered a customized photo album from Shutterfly two weeks ago for my mom.",
                "metadata": '{"session_id":"s2","timestamp":"2023/05/30 (Tue) 03:18"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Spring Sprint Triathlon, then took part in the Midsummer 5K Run" in sports_sheet
    assert "Deterministic temporal answer: 2 months." in comedy_sheet
    assert "Deterministic temporal answer: the photo album for my mom." in gift_sheet


def test_long_memory_aggregate_ledger_handles_plants_and_babies() -> None:
    plant_sheet = build_long_memory_full_fact_sheet(
        user_question="How many plants did I acquire in the last month?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I got a peace lily from the nursery two weeks ago along with a succulent.",
                "metadata": '{"session_id":"s1","timestamp":"2023/05/20 (Sat) 20:05"}',
            },
            {
                "id": 2,
                "content": "User: Should I repot my snake plant, which I got from my sister last month?",
                "metadata": '{"session_id":"s2","timestamp":"2023/05/25 (Thu) 16:59"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    baby_sheet = build_long_memory_full_fact_sheet(
        user_question="How many babies were born to friends and family members in the last few months?",
        all_rows=[
            {
                "id": 1,
                "content": "User: My cousin Rachel's son Max was born in March, and Charlotte was born around the same time. My aunt's twins, Ava and Lily, were born in April.",
                "metadata": '{"session_id":"s1","timestamp":"2023/05/13 (Sat) 02:13"}',
            },
            {
                "id": 2,
                "content": "User: David and his wife just had their third child, a baby boy named Jasper.",
                "metadata": '{"session_id":"s2","timestamp":"2023/05/13 (Sat) 14:49"}',
            },
            {
                "id": 3,
                "content": "User: My friend Sarah's adopted daughter Aaliyah is another birthday I want to remember.",
                "metadata": '{"session_id":"s3","timestamp":"2023/05/13 (Sat) 02:13"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Aggregate answer ledger (plant acquisitions)" in plant_sheet
    assert "Deterministic aggregate answer: 3." in plant_sheet
    assert "Aggregate answer ledger (babies born)" in baby_sheet
    assert "Deterministic aggregate answer: 5." in baby_sheet


def test_long_memory_aggregate_ledger_handles_bedtime_and_weddings() -> None:
    bedtime_sheet = build_long_memory_full_fact_sheet(
        user_question="What time did I go to bed on the day before I had a doctor's appointment?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I had a doctor's appointment at 10 AM last Thursday, and that's when I got the results.",
                "metadata": '{"session_id":"s1","timestamp":"2023/05/24 (Wed) 08:18"}',
            },
            {
                "id": 2,
                "content": "User: I didn't get to bed until 2 AM last Wednesday, which made Thursday morning a struggle.",
                "metadata": '{"session_id":"s2","timestamp":"2023/05/29 (Mon) 15:16"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    wedding_sheet = build_long_memory_full_fact_sheet(
        user_question="How many weddings have I attended in this year?",
        all_rows=[
            {
                "id": 1,
                "content": "User: My cousin Rachel's wedding at the vineyard was lovely; Mike looked so happy.",
                "metadata": '{"session_id":"s1","timestamp":"2023/10/15 (Sun) 05:48"}',
            },
            {
                "id": 2,
                "content": "User: My friend Emily finally got to tie the knot with her partner Sarah.",
                "metadata": '{"session_id":"s2","timestamp":"2023/10/15 (Sun) 04:44"}',
            },
            {
                "id": 3,
                "content": "User: I just got back from a friend's wedding last weekend; the bride Jen and her husband Tom were glowing.",
                "metadata": '{"session_id":"s3","timestamp":"2023/10/15 (Sun) 19:23"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Aggregate answer ledger (doctor appointment prior-night bedtime)" in bedtime_sheet
    assert "Deterministic aggregate answer: 2 AM." in bedtime_sheet
    assert "Aggregate answer ledger (weddings attended this year)" in wedding_sheet
    assert "Rachel and Mike, Emily and Sarah, and Jen and Tom" in wedding_sheet


def test_long_memory_aggregate_ledger_handles_baking_count() -> None:
    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="How many times did I bake something in the past two weeks?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I made the apple pie in my cast iron skillet and it turned out amazing!",
                "metadata": '{"session_id":"s1","timestamp":"2023/05/20 (Sat) 11:56"}',
            },
            {
                "id": 2,
                "content": "User: I recently baked a chocolate cake for my sister's birthday party.",
                "metadata": '{"session_id":"s2","timestamp":"2023/05/21 (Sun) 11:48"}',
            },
            {
                "id": 3,
                "content": "User: I made a delicious whole wheat baguette last Saturday.",
                "metadata": '{"session_id":"s3","timestamp":"2023/05/24 (Wed) 01:03"}',
            },
            {
                "id": 4,
                "content": "User: I used my oven's convection setting last Thursday to bake a batch of cookies.",
                "metadata": '{"session_id":"s4","timestamp":"2023/05/28 (Sun) 08:55"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Aggregate answer ledger (baking count)" in fact_sheet
    assert "Deterministic aggregate answer: 4." in fact_sheet


def test_long_memory_extract_answer_prefers_deterministic_aggregate_answer() -> None:
    fact_sheet = "Aggregate answer ledger (babies born):\n- Deterministic aggregate answer: 5."

    answer = MASESystem._extract_answer(
        "grounded_long_memory_aggregate_generalizer_english",
        "The answer is 6 because adopted children also count.",
        "How many babies were born to friends and family members in the last few months?",
        fact_sheet,
    )

    assert answer == "5."


def test_long_memory_extract_answer_prefers_deterministic_temporal_answer() -> None:
    fact_sheet = (
        "Temporal answer ledger (deterministic date math):\n"
        "- Deterministic temporal answer: 7 calendar days before the team meeting (or 8 inclusively)."
    )

    answer = MASESystem._extract_answer(
        "grounded_verify_lme_english",
        "There is not enough information in the fact sheet.",
        "How many days before the team meeting did I attend the workshop?",
        fact_sheet,
    )

    assert answer == "7 calendar days before the team meeting (or 8 inclusively)."


def test_long_context_candidate_table_keeps_long_context_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_context_qa")
    monkeypatch.setenv("MASE_LVEVAL_DATASET", "factrecall_en_128k")

    mode = select_executor_mode(
        "What is the name of the scientist widely acclaimed as the foundational figure of modern physics?",
        "Candidate table:\n[C1] name=David Beckham\n[C2] name=Ludwig Beethoven",
    )

    assert mode == "grounded_long_context_english"


def test_disambiguation_answer_is_collapsed_to_candidate_name() -> None:
    fact_sheet = (
        "Candidate table:\n"
        "[C1] name=David Beckham | evidence=...\n"
        "[C2] name=Ludwig Beethoven | evidence=..."
    )
    answer = MASESystem._extract_answer(
        "grounded_disambiguation_english_reasoning",
        (
            "The best-supported candidate from the fact sheet is Ludwig Beethoven, "
            "even though the surrounding text is adversarial."
        ),
        "What is the name of the scientist widely acclaimed as the foundational figure of modern physics?",
        fact_sheet,
    )

    assert answer == "Ludwig Beethoven"


def test_long_context_answer_with_candidate_table_is_collapsed_to_candidate_name() -> None:
    fact_sheet = (
        "Candidate table:\n"
        "[C1] name=David Beckham | evidence=...\n"
        "[C2] name=Ludwig Beethoven | evidence=..."
    )
    answer = MASESystem._extract_answer(
        "grounded_long_context_english",
        "The answer is Ludwig Beethoven because that planted candidate is the intended needle.",
        "What is the name of the scientist widely acclaimed as the foundational figure of modern physics?",
        fact_sheet,
    )

    assert answer == "Ludwig Beethoven"


def test_chinese_candidate_table_answer_is_collapsed_to_candidate_name() -> None:
    fact_sheet = (
        "候选裁决表：回答前必须逐项比较下面的候选名。\n"
        "[C1] name=贝多芬 | evidence=... 研究于物理理学 ... 现代物理学之奠基者 ...\n"
        "[C2] name=贝克汉姆 | evidence=... 现代天文之奠基者 ..."
    )
    answer = MASESystem._extract_answer(
        "grounded_long_context",
        "应选择贝多芬。",
        "被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？",
        fact_sheet,
    )

    assert answer == "贝多芬"


def test_chinese_candidate_table_still_collapses_to_mentioned_candidate() -> None:
    fact_sheet = (
        "候选裁决表：回答前必须逐项比较下面的候选名。\n"
        "[C1] name=贝多芬 | evidence=... 研究于物理理学 ... 现代物理学之奠基者 ...\n"
        "[C2] name=贝克汉姆 | evidence=... 现代天文之奠基者 ..."
    )
    answer = MASESystem._extract_answer(
        "grounded_long_context",
        "贝克汉姆",
        "被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？",
        fact_sheet,
    )

    assert answer == "贝克汉姆"


def test_single_chinese_candidate_table_answers_with_only_supported_name() -> None:
    fact_sheet = (
        "候选裁决表：回答前必须逐项比较下面的候选名。\n"
        "[C1] name=贝多芬 | evidence=... 研究于物理理学 ..."
    )
    answer = MASESystem._extract_answer(
        "grounded_long_context",
        "声名",
        "被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？",
        fact_sheet,
    )

    assert answer == "贝多芬"


def test_nolima_candidate_evidence_collapses_to_candidate_name() -> None:
    fact_sheet = (
        "NOLIMA CANDIDATE EVIDENCE (derived from the snippet; not gold):\n"
        "[C1] name=Veronica | direct_hits=lactose | evidence=... lactose intolerant ...\n"
        "[C2] name=Mandy | direct_hits=none | evidence=..."
    )
    answer = MASESystem._extract_answer(
        "grounded_nolima_main_english",
        "Veronica cannot drink milk because she is lactose intolerant.\n\nAnswer: Veronica",
        "Which character cannot drink milk?",
        fact_sheet,
    )

    assert answer == "Veronica"


def test_long_context_questions_use_long_context_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_context_qa")
    monkeypatch.setenv("MASE_LVEVAL_DATASET", "factrecall_en_128k")

    mode = verify_mode_for_question(
        "What is the name of the scientist widely acclaimed as the foundational figure of modern physics?"
    )

    assert mode == "grounded_verify_long_context_english"


def test_nolima_wrapper_uses_nolima_long_context_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_wrapper")
    monkeypatch.delenv("MASE_TASK_TYPE", raising=False)

    mode = select_executor_mode(
        "Which character cannot drink milk?",
        "A noisy book snippet with many names and places.",
    )

    assert mode == "grounded_nolima_main_english"


def test_nolima_extract_wrapper_uses_nolima_long_context_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_wrapper_extract")
    monkeypatch.delenv("MASE_TASK_TYPE", raising=False)

    mode = select_executor_mode(
        "Which character cannot drink milk?",
        "A noisy book snippet with many names and places.",
    )

    assert mode == "grounded_long_context_nolima_english"


def test_lme_temporal_qtype_uses_deepreason_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    mode = select_executor_mode(
        "How many weeks ago did I attend the friends and family sale at Nordstrom?",
        "[1] date=2022/11/18 ... Nordstrom friends and family sale ...",
    )

    assert mode == "grounded_long_memory_deepreason_english"


def test_lme_local_only_routes_away_from_cloud_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LOCAL_ONLY", "1")
    monkeypatch.setenv("MASE_LME_VERIFY", "1")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "multi-session")

    executor_mode = select_executor_mode("How many movies did I watch?", "[1] evidence")
    verifier_mode = verify_mode_for_question("How many movies did I watch?")
    generalizer_mode = generalizer_mode_for_question("How many movies did I watch?")

    assert local_only_models_enabled()
    assert executor_mode == "grounded_long_memory_english"
    assert verifier_mode == "grounded_verify_english_reasoning"
    assert generalizer_mode == "grounded_analysis_english_reasoning"


def test_model_interface_blocks_cloud_without_explicit_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MASE_ALLOW_CLOUD_MODELS", raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "models": {
                    "executor": {
                        "provider": "anthropic",
                        "model_name": "cloud-model",
                        "base_url": "https://example.invalid",
                        "api_key_env": "EXAMPLE_API_KEY",
                        "system_prompt": "test",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    model = ModelInterface(config_path)

    with pytest.raises(RuntimeError, match="Cloud model call blocked"):
        model.chat("executor", [{"role": "user", "content": "hello"}])


def test_lme_preference_qtype_uses_preference_generalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "single-session-preference")

    mode = generalizer_mode_for_question(
        "Can you recommend some resources where I can learn more about video editing?"
    )

    assert mode == "grounded_long_memory_preference_generalizer_english"


def test_lme_multisession_qtype_uses_aggregate_generalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "multi-session")

    mode = generalizer_mode_for_question(
        "How much total money have I spent on bike-related expenses since the start of the year?"
    )

    assert mode == "grounded_long_memory_aggregate_generalizer_english"


class _RoutingStub:
    def get_agent_config(self, agent_type: str):
        assert agent_type == "executor"
        return {"routing": {"default_collaboration_mode": "off"}}


def test_long_context_candidate_table_does_not_force_verify_collaboration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_context_qa")
    monkeypatch.setenv("MASE_LVEVAL_DATASET", "factrecall_en_128k")
    system = MASESystem.__new__(MASESystem)
    system.model_interface = _RoutingStub()  # type: ignore[attr-defined]

    mode = system._select_collaboration_mode(
        "What is the name of the scientist widely acclaimed as the foundational figure of modern physics?",
        "Candidate table:\n[C1] name=David Beckham\n[C2] name=Ludwig Beethoven",
        "grounded_long_context_english",
    )

    assert mode == "off"


def test_lme_preference_qtype_enables_split_collaboration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "single-session-preference")
    system = MASESystem.__new__(MASESystem)
    system.model_interface = _RoutingStub()  # type: ignore[attr-defined]

    mode = system._select_collaboration_mode(
        "Can you suggest a hotel for my upcoming trip to Miami?",
        "[1] date=2023/01/10 ... I like rooftop pools and ocean views ...",
        "grounded_long_memory_cloud_english",
    )

    assert mode == "split"


def test_lme_multisession_qtype_enables_split_collaboration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "multi-session")
    system = MASESystem.__new__(MASESystem)
    system.model_interface = _RoutingStub()  # type: ignore[attr-defined]

    mode = system._select_collaboration_mode(
        "How many model kits have I worked on or bought?",
        "[1] date=2023/04/28 ... model kit ...",
        "grounded_long_memory_cloud_english",
    )

    assert mode == "split"


def test_executor_prompt_includes_question_date_for_long_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/05/30 (Tue) 22:03")

    prompt = MASESystem._executor_prompt(
        "How many weeks ago did I attend the friends and family sale at Nordstrom?",
        "[1] date=2022/11/18 ... Nordstrom friends and family sale ...",
    )

    assert "QUESTION_DATE:" in prompt
    assert "2023/05/30 (Tue) 22:03" in prompt


# ---------------------------------------------------------------------------
# search_limit 128k bucket regression guard (25 → 30)
# ---------------------------------------------------------------------------

def test_long_context_search_limit_128k_returns_30(monkeypatch: pytest.MonkeyPatch) -> None:
    """128k bucket must return 30 (raised from 25) for better EN 128k retrieval."""
    monkeypatch.setenv("MASE_TASK_TYPE", "long_context_qa")
    monkeypatch.setenv("MASE_LVEVAL_DATASET", "factrecall_en_128k")
    assert long_context_search_limit() == 30


def test_long_context_search_limit_256k_still_returns_30(monkeypatch: pytest.MonkeyPatch) -> None:
    """256k bucket must remain at 30 — regression guard."""
    monkeypatch.setenv("MASE_TASK_TYPE", "long_context_qa")
    monkeypatch.setenv("MASE_LVEVAL_DATASET", "factrecall_en_256k")
    assert long_context_search_limit() == 30


def test_long_context_search_limit_smaller_buckets_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smaller buckets must not be affected by the 128k change."""
    for dataset, expected in [
        ("factrecall_en_16k", 12),
        ("factrecall_en_32k", 15),
        ("factrecall_en_64k", 20),
    ]:
        monkeypatch.setenv("MASE_LVEVAL_DATASET", dataset)
        assert long_context_search_limit() == expected, f"{dataset}: expected {expected}"


# ---------------------------------------------------------------------------
# multipass_allowed_for_task gate
# ---------------------------------------------------------------------------

def test_multipass_allowed_for_long_context_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    """long_context_qa tasks must be allowed to use multipass (EN LV-Eval path)."""
    monkeypatch.setenv("MASE_TASK_TYPE", "long_context_qa")
    assert multipass_allowed_for_task() is True


def test_multipass_allowed_for_long_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """long_memory tasks (LME) must also be allowed (LME scripts set MASE_MULTIPASS=1)."""
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    assert multipass_allowed_for_task() is True


def test_multipass_not_allowed_for_casual_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-benchmark tasks must NOT be allowed, so a stray env var can't activate
    the heavyweight pipeline in production."""
    monkeypatch.delenv("MASE_TASK_TYPE", raising=False)
    assert multipass_allowed_for_task() is False


def test_multipass_not_allowed_for_unknown_task_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "some_other_task")
    assert multipass_allowed_for_task() is False
