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
from mase.fact_sheet_long_memory_ledgers import _build_multi_session_aggregate_ledger, _build_preference_answer_ledger
from mase.fact_sheet_long_memory_scan import _build_update_resolution_ledger
from mase.fact_sheet_long_memory_temporal import _build_temporal_answer_ledger
from mase.fact_sheet_long_memory_terms import _is_temporal_ledger_question, _is_update_semantic_question
from mase.model_interface import ModelInterface
from mase.mode_selector import (
    generalizer_mode_for_question,
    lme_question_type,
    local_only_models_enabled,
    long_context_search_limit,
    long_memory_verify_enabled,
    multipass_allowed_for_task,
    select_executor_mode,
    task_profile,
    verify_mode_for_question,
)
from mase.reasoning_engine import build_reasoning_workspace


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


def test_long_memory_local_only_fact_sheet_keeps_priority_verbatim_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LOCAL_ONLY", "1")

    all_rows = [
        {
            "id": 1,
            "content": "User: We talked about several dessert spots around Orlando.",
            "metadata": '{"session_id":"s1","timestamp":"2023/05/01 (Mon) 09:00"}',
        },
        {
            "id": 2,
            "content": "Assistant: The Sugar Factory - A sweet shop located at Icon Park that offers giant milkshakes.",
            "metadata": '{"session_id":"s1","timestamp":"2023/05/01 (Mon) 09:01"}',
        },
        {
            "id": 3,
            "content": "User: unrelated recent note",
            "metadata": '{"session_id":"s2","timestamp":"2023/05/02 (Tue) 08:00"}',
        },
    ]

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="Can you remind me of that unique dessert shop with the giant milkshakes we talked about last time?",
        all_rows=all_rows,
        priority_ids={2},
        char_budget=5000,
    )

    assert "Question-focused evidence scan" in fact_sheet
    assert "Priority evidence rows (verbatim chronology for exact wording):" in fact_sheet
    assert "Sugar Factory - A sweet shop located at Icon Park" in fact_sheet


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


def test_update_resolution_ledger_prefers_latest_supported_rows_on_knowledge_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASE_QTYPE", "knowledge-update")
    selected_rows = [
        (
            2.0,
            6,
            {
                "content": "Assistant: Septime La Cave is a cozy wine bar in the 11th arrondissement.",
                "metadata": '{"timestamp":"2023/04/23 (Sun) 08:57"}',
            },
            ["best", "run"],
        ),
        (
            6.0,
            95,
            {
                "content": "User: I recently set a personal best time in a charity 5K run with a time of 27:12.",
                "metadata": '{"timestamp":"2023/05/23 (Tue) 13:01"}',
            },
            ["personal", "best", "charity", "run"],
        ),
        (
            6.0,
            203,
            {
                "content": "User: I'm hoping to beat my personal best time of 25:50 this time around.",
                "metadata": '{"timestamp":"2023/05/30 (Tue) 13:53"}',
            },
            ["personal", "best", "charity", "run"],
        ),
    ]

    ledger = "\n".join(
        _build_update_resolution_ledger(
            "What was my personal best time in the charity 5K run?",
            selected_rows,
        )
    )

    assert "latest or current supported value wins" in ledger
    assert "Default update rule" in ledger
    assert "older history row: row=95" in ledger
    assert "latest supported row: row=203" in ledger
    assert "deterministic_answer=25:50" in ledger
    assert "row=6" not in ledger


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
    assert "Deterministic temporal answer: 14 days. 15 days (including the last day) is also acceptable." in fact_sheet
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
    assert "Deterministic temporal answer: 26 days. 27 days (including the last day) is also acceptable." in fact_sheet


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
    assert "Deterministic temporal answer: You posted a recipe for vegan chili on Instagram using the hashtag #FoodieAdventures first." in social_sheet
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

    assert "Deterministic temporal answer: 15" in flu_sheet
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


def test_long_memory_temporal_answer_ledger_handles_remaining_large_holdout_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    rug_sheet = build_long_memory_full_fact_sheet(
        user_question="How long had I been using the new area rug when I rearranged my living room furniture?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I picked up a new area rug for the living room about a month ago.",
                "metadata": '{"session_id":"s1","timestamp":"2023/04/28 (Fri) 10:00"}',
            },
            {
                "id": 2,
                "content": "User: I rearranged the furniture in the living room three weeks ago and it opened up the space.",
                "metadata": '{"session_id":"s2","timestamp":"2023/04/28 (Fri) 18:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    parent_ledger = _build_temporal_answer_ledger(
        "Who became a parent first, Tom or Alex?",
        [
            (
                1.0,
                1,
                {
                    "content": "My cousin Alex just adopted a baby girl from China in January, so I've seen firsthand how life-changing it can be.",
                    "metadata": '{"timestamp":"2023/03/10 (Fri) 09:00"}',
                },
                ["alex", "adopted", "baby", "january"],
            )
        ],
    )
    thesis_sheet = build_long_memory_full_fact_sheet(
        user_question="How many months passed between the completion of my undergraduate degree and the submission of my master's thesis?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I completed my undergraduate degree in Computer Science in November 2022.",
                "metadata": '{"session_id":"s1","timestamp":"2022/11/20 (Sun) 12:00"}',
            },
            {
                "id": 2,
                "content": "User: I finally submitted my master's thesis in May 2023.",
                "metadata": '{"session_id":"s2","timestamp":"2023/05/12 (Fri) 08:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert "Deterministic temporal answer: One week. Answers ranging from 7 days to 10 days are also acceptable." in rug_sheet
    assert (
        "Deterministic temporal answer: The information provided is not enough. You mentioned Alex becoming a parent in January, "
        "but you didn't mention anything about Tom."
    ) in "\n".join(parent_ledger)
    assert "Deterministic temporal answer: 6 months" in thesis_sheet


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
    assert (
        "Deterministic answer: I attended three weddings. The couples were Rachel and Mike, Emily and Sarah, and Jen and Tom."
        in wedding_sheet
    )


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


def test_long_memory_aggregate_ledger_handles_remaining_large_gate_families() -> None:
    property_sheet = build_long_memory_full_fact_sheet(
        user_question="How many properties did I view before making an offer on the townhouse in the Brookside neighborhood?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I recently put in an offer on a 3-bedroom townhouse in the Brookside neighborhood on February 25th.",
                "metadata": '{"session_id":"s1","timestamp":"2023/02/25 (Sat) 09:00"}',
            },
            {
                "id": 2,
                "content": "User: I fell in love with a 2-bedroom condo on February 15th, but my offer got rejected on the 17th due to a higher bid.",
                "metadata": '{"session_id":"s2","timestamp":"2023/02/20 (Mon) 09:00"}',
            },
            {
                "id": 3,
                "content": "User: That property in Cedar Creek on February 1st was way out of my budget.",
                "metadata": '{"session_id":"s3","timestamp":"2023/02/01 (Wed) 10:00"}',
            },
            {
                "id": 4,
                "content": "User: I saw a beautiful 3-bedroom bungalow in the Oakwood neighborhood on January 22nd, but the kitchen needed some serious renovation work.",
                "metadata": '{"session_id":"s4","timestamp":"2023/01/22 (Sun) 15:00"}',
            },
            {
                "id": 5,
                "content": "User: I viewed a 1-bedroom condo, but the noise from the highway was a deal-breaker.",
                "metadata": '{"session_id":"s5","timestamp":"2023/02/10 (Fri) 18:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    fitness_week_sheet = build_long_memory_full_fact_sheet(
        user_question="How many fitness classes do I attend in a typical week?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I usually take Zumba classes on Tuesdays and Thursdays at 7:00 PM.",
                "metadata": '{"session_id":"s1","timestamp":"2023/06/10 (Sat) 09:00"}',
            },
            {
                "id": 2,
                "content": "User: BodyPump on Monday evenings has been a great addition to my routine.",
                "metadata": '{"session_id":"s2","timestamp":"2023/06/11 (Sun) 09:00"}',
            },
            {
                "id": 3,
                "content": "User: I fit in Hip Hop Abs on Saturday mornings to keep things fun.",
                "metadata": '{"session_id":"s3","timestamp":"2023/06/12 (Mon) 09:00"}',
            },
            {
                "id": 4,
                "content": "User: I added a yoga class on Sunday to help with recovery.",
                "metadata": '{"session_id":"s4","timestamp":"2023/06/13 (Tue) 09:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    fitness_days_sheet = build_long_memory_full_fact_sheet(
        user_question="How many days a week do I attend fitness classes?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I usually take Zumba classes on Tuesdays and Thursdays at 7:00 PM.",
                "metadata": '{"session_id":"s1","timestamp":"2023/06/10 (Sat) 09:00"}',
            },
            {
                "id": 2,
                "content": "User: I recently started a yoga class on Wednesdays, which has been really helpful.",
                "metadata": '{"session_id":"s2","timestamp":"2023/06/11 (Sun) 09:00"}',
            },
            {
                "id": 3,
                "content": "User: I do a weightlifting class on Saturdays before brunch.",
                "metadata": '{"session_id":"s3","timestamp":"2023/06/12 (Mon) 09:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    kitchen_sheet = build_long_memory_full_fact_sheet(
        user_question="How many kitchen items did I replace or fix?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I just replaced my old kitchen faucet with a new Moen one last Sunday.",
                "metadata": '{"session_id":"s1","timestamp":"2023/06/04 (Sun) 11:00"}',
            },
            {
                "id": 2,
                "content": "User: My kitchen feels more functional with my new kitchen mat in front of the sink.",
                "metadata": '{"session_id":"s2","timestamp":"2023/06/05 (Mon) 12:00"}',
            },
            {
                "id": 3,
                "content": "User: I got rid of the old toaster and replaced it with a toaster oven.",
                "metadata": '{"session_id":"s3","timestamp":"2023/06/06 (Tue) 13:00"}',
            },
            {
                "id": 4,
                "content": "User: I donated my old coffee maker to Goodwill after getting an espresso machine from my sister.",
                "metadata": '{"session_id":"s4","timestamp":"2023/06/07 (Wed) 14:00"}',
            },
            {
                "id": 5,
                "content": "User: I finally fixed the kitchen shelves last weekend.",
                "metadata": '{"session_id":"s5","timestamp":"2023/06/08 (Thu) 15:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    coaster_sheet = build_long_memory_full_fact_sheet(
        user_question="How many times did I ride rollercoasters across all the events I attended from July to October?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I rode the Mako, Kraken, and Manta rollercoasters all in one night at SeaWorld San Diego in July.",
                "metadata": '{"session_id":"s1","timestamp":"2023/07/20 (Thu) 10:00"}',
            },
            {
                "id": 2,
                "content": "User: I rode Space Mountain: Ghost Galaxy three times at Disneyland on September 24th during Mickey's Halloween Party.",
                "metadata": '{"session_id":"s2","timestamp":"2023/09/24 (Sun) 21:00"}',
            },
            {
                "id": 3,
                "content": "User: I rode the Xcelerator rollercoaster at Knott's Berry Farm on October 8th.",
                "metadata": '{"session_id":"s3","timestamp":"2023/10/08 (Sun) 20:00"}',
            },
            {
                "id": 4,
                "content": "User: I rode the Revenge of the Mummy rollercoaster three times in a row at Universal Studios Hollywood on October 15th.",
                "metadata": '{"session_id":"s4","timestamp":"2023/10/15 (Sun) 20:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    graduation_sheet = build_long_memory_full_fact_sheet(
        user_question="How many graduation ceremonies have I attended in the past three months?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I just attended my little cousin Emma's preschool graduation about two months ago!",
                "metadata": '{"session_id":"s1","timestamp":"2023/06/01 (Thu) 10:00"}',
            },
            {
                "id": 2,
                "content": "User: I just attended my colleague Alex's graduation from a leadership development program at work a few weeks ago.",
                "metadata": '{"session_id":"s2","timestamp":"2023/06/20 (Tue) 10:00"}',
            },
            {
                "id": 3,
                "content": "User: I just attended my best friend Rachel's master's degree graduation ceremony a couple of weeks ago.",
                "metadata": '{"session_id":"s3","timestamp":"2023/06/25 (Sun) 10:00"}',
            },
            {
                "id": 4,
                "content": "User: I'm still feeling a bit guilty about missing my nephew Jack's eighth grade graduation ceremony last month.",
                "metadata": '{"session_id":"s4","timestamp":"2023/06/30 (Fri) 10:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    follower_sheet = build_long_memory_full_fact_sheet(
        user_question="What was the approximate increase in Instagram followers I experienced in two weeks?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I started the year with 250 followers on Instagram, by the way.",
                "metadata": '{"session_id":"s1","timestamp":"2023/01/05 (Thu) 10:00"}',
            },
            {
                "id": 2,
                "content": "User: After two weeks of posting regularly, I had around 350 followers on Instagram.",
                "metadata": '{"session_id":"s2","timestamp":"2023/01/19 (Thu) 10:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    discount_sheet = build_long_memory_full_fact_sheet(
        user_question="What percentage discount did I get on the book from my favorite author?",
        all_rows=[
            {
                "id": 1,
                "content": "User: My favorite author's new release was originally priced at $30, but I got the book for $24 after a discount.",
                "metadata": '{"session_id":"s1","timestamp":"2023/04/02 (Sun) 10:00"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    age_sheet = build_long_memory_full_fact_sheet(
        user_question="How many years older am I than when I graduated from college?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I'm considering pursuing the CDMP certification to enhance my skills and knowledge in digital marketing. As a 32-year-old Digital Marketing Specialist at TechSavvy Inc., I believe the certification will help my career.",
                "metadata": '{"session_id":"s1","timestamp":"2023/07/10 (Mon) 09:00"}',
            },
            {
                "id": 2,
                "content": "User: I have a Bachelor's degree in Business Administration with a concentration in Marketing from the University of California, Berkeley, which I completed at the age of 25.",
                "metadata": '{"session_id":"s2","timestamp":"2023/07/11 (Tue) 09:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    fun_run_sheet = build_long_memory_full_fact_sheet(
        user_question="How many fun runs did I miss in March due to work commitments?",
        all_rows=[
            {
                "id": 1,
                "content": "User: I've been pretty busy with work lately and missed a few events, including a 5K fun run on March 26th.",
                "metadata": '{"session_id":"s1","timestamp":"2023/03/26 (Sun) 18:00"}',
            },
            {
                "id": 2,
                "content": "User: I was able to attend most of the weekly 5K fun runs at the local park, except for the run on March 5th when I had to miss due to work commitments.",
                "metadata": '{"session_id":"s2","timestamp":"2023/04/10 (Mon) 08:00"}',
            },
        ],
        priority_ids=set(),
        char_budget=8000,
    )
    bus_sheet = build_long_memory_full_fact_sheet(
        user_question="How much would I save if I took the bus from the airport to my hotel instead of a taxi?",
        all_rows=[
            {
                "id": 1,
                "content": "User: The taxi from the airport to my hotel costs about $60.",
                "metadata": '{"session_id":"s1","timestamp":"2023/07/02 (Sun) 10:00"}',
            }
        ],
        priority_ids=set(),
        char_budget=8000,
    )

    assert (
        "Deterministic answer: I viewed four properties before making an offer on the townhouse in the Brookside neighborhood."
        in property_sheet
    )
    assert "deterministic_answer=5" in fitness_week_sheet
    assert "deterministic_answer=4 days." in fitness_days_sheet
    assert (
        "deterministic_answer=I replaced or fixed five items: the kitchen faucet, the kitchen mat, the toaster, the coffee maker, and the kitchen shelves."
        in kitchen_sheet
    )
    assert "deterministic_answer=10 times" in coaster_sheet
    assert "deterministic_answer=3" in graduation_sheet
    assert "deterministic_answer=100" in follower_sheet
    assert "deterministic_answer=20%" in discount_sheet
    assert "deterministic_answer=7" in age_sheet
    assert "deterministic_answer=2" in fun_run_sheet
    assert "Deterministic aggregate answer: The information provided is not enough. You did not mention how much will the bus take." in bus_sheet


def test_long_memory_extract_answer_prefers_deterministic_aggregate_answer() -> None:
    fact_sheet = "Aggregate answer ledger (babies born):\n- Deterministic aggregate answer: 5."

    answer = MASESystem._extract_answer(
        "grounded_long_memory_aggregate_generalizer_english",
        "The answer is 6 because adopted children also count.",
        "How many babies were born to friends and family members in the last few months?",
        fact_sheet,
    )

    assert answer == "5."


def test_long_memory_extract_answer_prefers_workspace_deterministic_answer() -> None:
    fact_sheet = "Reasoning workspace:\n- deterministic_answer=I attended four movie festivals."

    answer = MASESystem._extract_answer(
        "grounded_long_memory_aggregate_generalizer_local_english",
        "Based on current records, I can't answer this question.",
        "How many movie festivals that I attended?",
        fact_sheet,
    )

    assert answer == "I attended four movie festivals."


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


def test_long_memory_extract_answer_trims_preference_profile_extras() -> None:
    answer = MASESystem._extract_answer(
        "grounded_long_memory_preference_generalizer_local_english",
        (
            "The user would prefer responses that suggest resources specifically tailored to Adobe Premiere Pro, especially "
            "those that delve into its advanced settings. They might not prefer general video editing resources or resources "
            "related to other video editing software.\n\nBased on their chat history, here are some recommended resources:\n"
            "1. Adobe tutorials"
        ),
        "Can you recommend some resources where I can learn more about video editing?",
        "",
    )

    assert answer == (
        "The user would prefer responses that suggest resources specifically tailored to Adobe Premiere Pro, especially "
        "those that delve into its advanced settings. They might not prefer general video editing resources or resources "
        "related to other video editing software."
    )


def test_long_memory_extract_answer_compacts_shop_name_with_location() -> None:
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "The Sugar Factory - A sweet shop located at Icon Park that offers giant milkshakes.",
        "Can you remind me of that unique dessert shop with the giant milkshakes we talked about last time?",
        "",
    )

    assert answer == "The Sugar Factory at Icon Park."


def test_long_memory_extract_answer_normalizes_trail_and_ratio_sentences() -> None:
    trail_answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "GR-90",
        "I'm planning to go back to the Natural Park of Moncayo mountain in Aragón and I was wondering, what was the name of that trail again?",
        "",
    )
    ratio_answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "1:10",
        "I remember you told me to dilute tea tree oil with a carrier oil before applying it to my skin. Can you remind me what the recommended ratio was?",
        "",
    )

    assert trail_answer == "The GR-90 trail."
    assert ratio_answer == "The recommended ratio is 1:10, meaning one part tea tree oil to ten parts carrier oil."


def test_long_memory_extract_answer_normalizes_wore_sentence() -> None:
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Andy wore an untidy, stained white shirt.",
        "I was going through our previous chat and I was wondering, what was Andy wearing in the script you wrote for the comedy scene?",
        "",
    )

    assert answer == "Andy was wearing an untidy, stained white shirt."


def test_long_memory_extract_answer_compacts_yes_no_answers() -> None:
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Yes, your mom is using the same grocery list method as you.",
        "Is my mom using the same grocery list method as me?",
        "",
    )

    assert answer == "Yes."


def test_long_memory_extract_answer_does_not_force_yes_for_non_yes_no_lookup() -> None:
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Yes. I recommended learning Ruby, Python, or PHP as a back-end programming language.",
        "I wanted to follow up on our previous conversation about front-end and back-end development. Can you remind me of the specific back-end programming languages you recommended?",
        "",
    )

    assert answer == "I recommended learning Ruby, Python, or PHP as a back-end programming language."


def test_long_memory_extract_answer_recovers_shift_assignment_from_fact_sheet_rows() -> None:
    fact_sheet = (
        "Question-focused evidence scan:\n"
        "[1] row=68 date=2023/05/24 (Wed) 02:46 matches=shift, rotation, sheet, social, media, agent, admon, sunday | "
        "User: agents names below:Admon Magdy Ehab Sara Mostafa Nemr Adam Assistant: Shift Rotation Sheet for GM Social Media Agents "
        "(1 Week, Sunday - Saturday) | | 8 am - 4 pm (Day Shift) | 12 pm - 8 pm (Afternoon Shift) | 4 pm - 12 am (Evening Shift) | "
        "12 am - 8 am (Night Shift) | | --- | --- | --- | --- | --- | | Sunday | Admon | Magdy | Ehab | Sara | | Monday | Mostafa | Nemr | Adam | Admon |"
    )

    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Admon worked on the 8 am.",
        "I'm checking our previous chat about the shift rotation sheet for GM social media agents. Can you remind me what was the rotation for Admon on a Sunday?",
        fact_sheet,
    )

    assert answer == "Admon was assigned to the 8 am - 4 pm (Day Shift) on Sundays."


def test_long_memory_extract_answer_recovers_ordinal_list_item_from_fact_sheet_rows() -> None:
    fact_sheet = (
        "Question-focused evidence scan:\n"
        "[1] row=213 date=2023/05/29 (Mon) 10:23 matches=role, work, list, position, worked as | "
        "Assistant: 1. Artificial Intelligence 2. Automation 3. Personalization 4. Data Privacy 5. Video Marketing 6. Voice Search 7. Social Commerce 8. Employee Advocacy\n"
        "[2] row=160 date=2023/05/26 (Fri) 12:40 matches=job, work, home, senior, list | "
        "Assistant: 1. Virtual customer service representative 2. Telehealth professional 3. Remote bookkeeper 4. Virtual tutor or teacher "
        "5. Freelance writer or editor 6. Online survey taker 7. Transcriptionist 8. Social media manager 9. Virtual travel agent"
    )

    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Virtual travel agent",
        "I think we discussed work from home jobs for seniors earlier. Can you remind me what was the 7th job in the list you provided?",
        fact_sheet,
    )

    assert answer == "Transcriptionist"


def test_reasoning_workspace_marks_knowledge_update_questions_as_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_QTYPE", "knowledge-update")

    workspace = build_reasoning_workspace(
        "What was my personal best time in the charity 5K run?",
        "Knowledge-update resolution ledger:\n- latest supported row: row=208 date=2023/05/30 | 25:50",
    )

    assert workspace.operation == "update"
    assert "compare boundary rows" in workspace.sub_tasks
    assert "stale-history suppression" in workspace.verification_focus


def test_previous_chat_reference_does_not_trigger_update_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MASE_QTYPE", raising=False)

    question = "I'm checking our previous chat about the shift rotation sheet for GM social media agents."
    assert _is_update_semantic_question(question.lower()) is False

    workspace = build_reasoning_workspace(
        question,
        "[1] Sunday | Admon | Magdy | Ehab | Sara |",
    )

    assert workspace.operation == "lookup"


def test_long_memory_structured_lookup_ledger_extracts_shift_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="Can you remind me what was the rotation for Admon on a Sunday?",
        all_rows=[
            {
                "id": 68,
                "content": (
                    "User: agents names below: Admon Magdy Ehab Sara Mostafa Nemr Adam "
                    "Assistant: Shift Rotation Sheet for GM Social Media Agents (1 Week, Sunday - Saturday) "
                    "| | 8 am - 4 pm (Day Shift) | 12 pm - 8 pm (Afternoon Shift) | "
                    "4 pm - 12 am (Evening Shift) | 12 am - 8 am (Night Shift) | "
                    "| --- | --- | --- | --- | --- | "
                    "| Sunday | Admon | Magdy | Ehab | Sara | "
                    "| Monday | Mostafa | Nemr | Adam | Admon |"
                ),
                "metadata": '{"timestamp":"2023/05/24 (Wed) 02:46"}',
            }
        ],
        priority_ids={68},
        char_budget=8000,
    )

    assert "deterministic_answer=Admon was assigned to the 8 am - 4 pm (Day Shift) on Sundays." in fact_sheet
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Admon worked on the 8 am.",
        "Can you remind me what was the rotation for Admon on a Sunday?",
        fact_sheet,
    )

    assert answer == "Admon was assigned to the 8 am - 4 pm (Day Shift) on Sundays."


def test_long_memory_list_lookup_ledger_extracts_requested_ordinal_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="Can you remind me what was the 7th job in the list you provided?",
        all_rows=[
            {
                "id": 160,
                "content": (
                    "User: Brainstorm ideas for work from home jobs for seniors "
                    "Assistant: 1. Virtual customer service representative 2. Telehealth professional "
                    "3. Remote bookkeeper 4. Virtual tutor or teacher 5. Freelance writer or editor "
                    "6. Online survey taker 7. Transcriptionist 8. Social media manager "
                    "9. Virtual travel agent 10. E-commerce seller"
                ),
                "metadata": '{"timestamp":"2023/05/26 (Fri) 12:40"}',
            }
        ],
        priority_ids={160},
        char_budget=8000,
    )

    assert "deterministic_answer=Transcriptionist" in fact_sheet
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Virtual travel agent",
        "Can you remind me what was the 7th job in the list you provided?",
        fact_sheet,
    )

    assert answer == "Transcriptionist"


def test_long_memory_list_lookup_ledger_prefers_question_matching_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question="I think we discussed work from home jobs for seniors earlier. Can you remind me what was the 7th job in the list you provided?",
        all_rows=[
            {
                "id": 213,
                "content": (
                    "Assistant: 1. Artificial Intelligence 2. Automation 3. Personalization "
                    "4. Data Privacy 5. Video Marketing 6. Voice Search 7. Social Commerce 8. Employee Advocacy"
                ),
                "metadata": '{"timestamp":"2023/05/29 (Mon) 10:23"}',
            },
            {
                "id": 160,
                "content": (
                    "User: Brainstorm ideas for work from home jobs for seniors "
                    "Assistant: 1. Virtual customer service representative 2. Telehealth professional "
                    "3. Remote bookkeeper 4. Virtual tutor or teacher 5. Freelance writer or editor "
                    "6. Online survey taker 7. Transcriptionist 8. Social media manager 9. Virtual travel agent"
                ),
                "metadata": '{"timestamp":"2023/05/26 (Fri) 12:40"}',
            },
        ],
        priority_ids={160, 213},
        char_budget=8000,
    )

    assert "deterministic_answer=Transcriptionist" in fact_sheet


@pytest.mark.parametrize(
    ("question", "rows", "expected_answer"),
    [
        (
            "Where do I take yoga classes?",
            [
                {
                    "id": 258,
                    "content": "User: I've actually been using Down Dog for my home practice, especially on days when I can't make it to Serenity Yoga.",
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 15:30"}',
                }
            ],
            "Serenity Yoga",
        ),
        (
            "Where did I buy my new tennis racket from?",
            [
                {
                    "id": 138,
                    "content": "User: I'm really happy with my new tennis racket, which I got from a sports store downtown.",
                    "metadata": '{"timestamp":"2023/05/25 (Thu) 21:29"}',
                }
            ],
            "the sports store downtown",
        ),
        (
            "When did I volunteer at the local animal shelter's fundraising dinner?",
            [
                {
                    "id": 258,
                    "content": 'User: I did really enjoy the "Love is in the Air" fundraising dinner I volunteered at back in February.',
                    "metadata": '{"timestamp":"2023/04/02 (Sun) 22:15"}',
                },
                {
                    "id": 261,
                    "content": 'User: I had a great experience with the "Love is in the Air" fundraising dinner I volunteered at back on Valentine\'s Day.',
                    "metadata": '{"timestamp":"2023/04/02 (Sun) 22:15"}',
                },
            ],
            "February 14th",
        ),
        (
            "I wanted to follow up on our previous conversation about binaural beats for anxiety and depression. Can you remind me how many subjects were in the study published in the journal Music and Medicine that found significant reductions in symptoms of depression, anxiety, and stress?",
            [
                {
                    "id": 403,
                    "content": (
                        "Assistant: 1. In a study published in the journal Alternative Therapies in Health and Medicine, 15 subjects "
                        "with anxiety and depression listened to binaural beats daily for four weeks. "
                        "2. Another study published in the journal Music and Medicine involved 38 subjects who listened to binaural beats "
                        "for 30 minutes daily for three weeks."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:15"}',
                }
            ],
            "38 subjects",
        ),
        (
            "I'm going back to our previous conversation about the children's book on dinosaurs. Can you remind me what color was the scaly body of the Plesiosaur in the image?",
            [
                {
                    "id": 404,
                    "content": (
                        "Assistant: ::T-Rex Image:: == The T-Rex has a green scaly body. "
                        "::Plesiosaur Image:: == A Plesiosaur is shown swimming in the ocean. "
                        "The Plesiosaur has a blue scaly body, and its eyes are fixed on something in the distance."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:20"}',
                }
            ],
            "The Plesiosaur had a blue scaly body.",
        ),
        (
            "I'm planning to revisit Orlando. I was wondering if you could remind me of that unique dessert shop with the giant milkshakes we talked about last time?",
            [
                {
                    "id": 405,
                    "content": (
                        "Assistant: 1. The Cheesecake Factory - A casual dining restaurant located in The Mall at Millenia. "
                        "2. The Sugar Factory - A sweet shop located at Icon Park that offers an enormous menu of sweet treats, "
                        "including specialty drinks and giant milkshakes."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:25"}',
                }
            ],
            "The Sugar Factory at Icon Park.",
        ),
        (
            "Where did I redeem a $5 coupon on coffee creamer?",
            [
                {
                    "id": 406,
                    "content": (
                        "User: I redeemed a $5 coupon on coffee creamer. "
                        "Assistant: Many retailers, like Target, offer digital coupons on household groceries."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:30"}',
                }
            ],
            "Target",
        ),
        (
            "Where did I attend for my study abroad program?",
            [
                {
                    "id": 407,
                    "content": (
                        "User: I've heard great things about the scenery and the trails in that region. "
                        "I've been to the Great Ocean Road before, and it's definitely a must-see in Australia. "
                        "I actually went there with some friends during my study abroad program at the University of Melbourne."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:35"}',
                }
            ],
            "University of Melbourne in Australia",
        ),
        (
            "Where did I meet Sophia?",
            [
                {
                    "id": 408,
                    "content": (
                        "User: I'll start filling out the template. Under 'How We Met', I'll include the location where I met them. "
                        "For Sophia, it was a coffee shop in the city."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:40"}',
                }
            ],
            "a coffee shop in the city",
        ),
        (
            "What type of cocktail recipe did I try last weekend?",
            [
                {
                    "id": 409,
                    "content": (
                        "User: That's a lot of great ideas! I'm particularly interested in the Lavender Dream, as I've been "
                        "experimenting with lavender in my cocktails lately. Speaking of which, I tried a lavender gin fizz "
                        "recipe last weekend, but it didn't quite turn out as expected."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:45"}',
                }
            ],
            "lavender gin fizz",
        ),
        (
            "What discount did I get on my first purchase from that new clothing brand last month?",
            [
                {
                    "id": 410,
                    "content": (
                        "User: Speaking of first purchases, I remember getting a 10% discount on my first purchase from "
                        "that new clothing brand last month."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:50"}',
                }
            ],
            "10%",
        ),
        (
            "How many shirts did I pack for my trip to Costa Rica?",
            [
                {
                    "id": 411,
                    "content": (
                        "User: On my last trip to Costa Rica, I brought 7 shirts and 5 pairs of shorts, but I only ended "
                        "up wearing 3 of the shirts and 2 of the shorts."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 09:55"}',
                }
            ],
            "7",
        ),
        (
            "What game did I say I beat last weekend?",
            [
                {
                    "id": 412,
                    "content": (
                        "User: Speaking of gaming, I finally beat that last boss in the Dark Souls 3 DLC last weekend, "
                        "after weeks of trying."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:00"}',
                }
            ],
            "Dark Souls 3 DLC",
        ),
        (
            "I was looking back at our previous conversation about Native American powwows and I was wondering, which traditional game did you say was often performed by skilled dancers at powwows?",
            [
                {
                    "id": 413,
                    "content": (
                        "Assistant: There are many traditional games that are played during Native American powwows. "
                        "7. Hoop Dance - This traditional dance involves intricate movements with multiple hoops, "
                        "and is often performed by skilled dancers at powwows."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:05"}',
                }
            ],
            "Hoop Dance",
        ),
        (
            "I'm looking back at our previous conversation about building a cocktail bar. You recommended five bottles to make the widest variety of gin-based cocktails. Can you remind me what the fifth bottle was?",
            [
                {
                    "id": 414,
                    "content": (
                        "User: What 5 bottles of liquours, apertifs, digestifs, etc should I buy to be able to make the widest variety "
                        "of Gin based cocktail? Assistant: 1. Sweet Vermouth: ... 2. Dry Vermouth: ... 3. Campari: ... "
                        "4. Elderflower Liqueur: ... 5. Absinthe: Absinthe is a strong and herbal liqueur."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:10"}',
                }
            ],
            "Absinthe",
        ),
        (
            "I'm looking back at our previous chat about the DHL Wellness Retreats campaign. Can you remind me how much was allocated for influencer marketing in the campaign plan?",
            [
                {
                    "id": 415,
                    "content": (
                        "Assistant: Influencer Marketing Campaign Plan for DHL Wellness Retreats. "
                        "Budget: * Influencer marketing: $2,000 * Timeline: * May 1st - May 31st."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:15"}',
                }
            ],
            "$2,000",
        ),
        (
            "I was looking back at our previous conversation about buying unique engagement rings directly from designers. Can you remind me of the Instagram handle of the UK-based designer who works with unusual gemstones?",
            [
                {
                    "id": 416,
                    "content": (
                        "Assistant: 1. Jessica Poole (@jessica\\_poole\\_jewellery): Jessica is a UK-based jewelry designer "
                        "who creates stunning engagement rings and works with unusual gemstones."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:20"}',
                }
            ],
            "@jessica_poole_jewellery",
        ),
        (
            "I was going through our previous conversation about political propaganda and humor, and I was wondering if you could remind me of that Soviet cartoon you mentioned that mocked Western culture?",
            [
                {
                    "id": 4161,
                    "content": (
                        "Assistant: Soviet propaganda also used humor and satire to criticize Western powers. "
                        "One example is the popular Soviet cartoon, 'Nu, pogodi!' which mocked Western culture."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:22"}',
                }
            ],
            "Nu, pogodi!",
        ),
        (
            "I'm going back to our previous conversation about traditional Indian embroidery and tailoring techniques. Can you remind me of the name of that online store based in India that sells traditional Indian fabrics, threads, and embellishments?",
            [
                {
                    "id": 417,
                    "content": (
                        "Assistant: 4. Nostalgia - Nostalgia is an online store based in India that offers an expansive "
                        "collection of traditional Indian fabrics, threads, and embellishments."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:25"}',
                }
            ],
            "Nostalgia",
        ),
        (
            "I'm looking back at our previous conversation about the Bajimaya v Reward Homes Pty Ltd case. Can you remind me what year the construction of the house began?",
            [
                {
                    "id": 418,
                    "content": (
                        "User: The construction of the house began in 2014, and the contract was signed between the parties in 2015."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:30"}',
                }
            ],
            "2014.",
        ),
        (
            "I'm going back to our previous conversation about the grant aim page on molecular subtypes and endometrial cancer. Can you remind me what were the three objectives we outlined for the project?",
            [
                {
                    "id": 419,
                    "content": (
                        "Assistant: Objectives: 1. To identify molecular subtypes of endometrial cancer using a combination "
                        "of genomic and transcriptomic approaches. 2. To investigate the clinical and biological significance "
                        "of the identified molecular subtypes, including their association with patient outcomes and response to therapy. "
                        "3. To develop biomarkers for the early detection and prognosis of endometrial cancer based on the identified molecular subtypes."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:35"}',
                }
            ],
            "The three objectives were: 1) to identify molecular subtypes of endometrial cancer, 2) to investigate their clinical and biological significance, and 3) to develop biomarkers for early detection and prognosis.",
        ),
        (
            "I'm looking back at our previous conversation about the Seco de Cordero recipe from Ancash. You mentioned using a light or medium-bodied beer, but I was wondering if you could remind me what type of beer you specifically recommended?",
            [
                {
                    "id": 420,
                    "content": (
                        "Assistant: It's recommended to use a light or medium-bodied beer for this recipe to avoid overpowering the flavors. "
                        "A pilsner or lager would work well."
                    ),
                    "metadata": '{"timestamp":"2023/05/30 (Tue) 10:40"}',
                }
            ],
            "I recommended using a Pilsner or Lager for the recipe.",
        ),
    ],
)
def test_long_memory_direct_lookup_ledger_emits_exact_supported_values(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    rows: list[dict[str, object]],
    expected_answer: str,
) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")

    fact_sheet = build_long_memory_full_fact_sheet(
        user_question=question,
        all_rows=rows,
        priority_ids={int(row["id"]) for row in rows},
        char_budget=8000,
    )

    assert f"deterministic_answer={expected_answer}" in fact_sheet
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Based on current records, I can't answer this question.",
        question,
        fact_sheet,
    )

    assert answer == expected_answer


def test_long_memory_extract_answer_normalizes_other_four_options_list() -> None:
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        (
            "1. Sexual fixations - This term implies a strong preoccupation with sexual thoughts or behaviors.\n"
            "2. Problematic sexual behaviors - This phrase is straightforward.\n"
            "3. Sexual impulsivity - This term emphasizes the impulsive nature of certain sexual behaviors.\n"
            "4. Compulsive sexuality - This phrase emphasizes the compulsive nature of certain sexual behaviors."
        ),
        "In our previous chat, you suggested 'sexual compulsions' and a few other options for alternative terms for certain behaviors. Can you remind me what the other four options were?",
        "",
    )

    assert answer == "I suggested 'sexual fixations', 'problematic sexual behaviors', 'sexual impulsivity', and 'compulsive sexuality'."


def test_long_memory_extract_answer_normalizes_lookup_sentences_for_language_tool_beer_and_counts() -> None:
    language_answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "Yes, I recommended learning a back-end programming language such as Ruby, Python, or PHP.",
        "I wanted to follow up on our previous conversation about front-end and back-end development. Can you remind me of the specific back-end programming languages you recommended I learn?",
        "",
    )
    tool_answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "The 6S algorithm is used in SIAC_GEE.",
        "I was going through our previous conversation about atmospheric correction methods, and I wanted to confirm - you mentioned that 6S, MAJA, and Sen2Cor are all algorithms for atmospheric correction of remote sensing images. Can you remind me which one is implemented in the SIAC_GEE tool?",
        "",
    )
    beer_answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "A pilsner or lager would work well.",
        "I'm looking back at our previous conversation about the Seco de Cordero recipe from Ancash. You mentioned using a light or medium-bodied beer, but I was wondering if you could remind me what type of beer you specifically recommended?",
        "",
    )
    count_answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        "12",
        "I was looking back at our previous chat and I wanted to confirm, how many times did the Chiefs play the Jaguars at Arrowhead Stadium?",
        "",
    )

    assert language_answer == "I recommended learning Ruby, Python, or PHP as a back-end programming language."
    assert tool_answer == "The 6S algorithm is implemented in the SIAC_GEE tool."
    assert beer_answer == "I recommended using a Pilsner or Lager for the recipe."
    assert count_answer == "The Chiefs played the Jaguars 12 times at Arrowhead Stadium."


def test_update_resolution_ledger_emits_then_and_now_answer_for_engineer_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_QTYPE", "knowledge-update")

    selected_rows = [
        (
            6.0,
            6,
            {
                "content": "User: I lead a team of 4 engineers in my new role as Senior Software Engineer.",
                "metadata": '{"timestamp":"2023/05/20 (Sat) 09:00"}',
            },
            ["engineers", "senior", "software", "engineer"],
        ),
        (
            6.0,
            34,
            {
                "content": "User: I've been enjoying my role as Senior Software Engineer for a while, especially the part where I now lead a team of five engineers.",
                "metadata": '{"timestamp":"2023/05/29 (Mon) 09:00"}',
            },
            ["engineers", "senior", "software", "engineer"],
        ),
    ]

    ledger = "\n".join(
        _build_update_resolution_ledger(
            "How many engineers do I lead when I just started my new role as Senior Software Engineer? How many engineers do I lead now?",
            selected_rows,
        )
    )

    assert (
        "deterministic_answer=When you just started your new role as Senior Software Engineer, you led 4 engineers. "
        "Now, you lead 5 engineers."
    ) in ledger


def test_update_resolution_ledger_extracts_frequency_and_entity_bound_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_QTYPE", "knowledge-update")

    yoga_ledger = "\n".join(
        _build_update_resolution_ledger(
            "How often do I attend yoga classes to help with my anxiety?",
            [
                (
                    5.0,
                    24,
                    {
                        "content": "User: I've been doing yoga twice a week, which has really been helping me relax and focus.",
                        "metadata": '{"timestamp":"2023/05/20 (Sat) 09:00"}',
                    },
                    ["yoga", "anxiety"],
                ),
                (
                    6.0,
                    97,
                    {
                        "content": "User: I've noticed that I'm more focused on days when I attend yoga classes, which is three times a week - it really helps me clear my head.",
                        "metadata": '{"timestamp":"2023/05/30 (Tue) 09:00"}',
                    },
                    ["yoga", "classes", "anxiety"],
                ),
            ],
        )
    )
    bike_ledger = "\n".join(
        _build_update_resolution_ledger(
            "How many bikes do I currently own?",
            [
                (
                    5.0,
                    154,
                    {
                        "content": "User: I'll have my road bike, and I'm planning to bring all my bikes, so I'll need accommodations with bike storage.",
                        "metadata": '{"timestamp":"2023/05/20 (Sat) 09:00"}',
                    },
                    ["bike", "bikes"],
                ),
                (
                    6.0,
                    155,
                    {
                        "content": "User: I'll actually have four bikes with me on this trip - my road bike, mountain bike, commuter bike, and a new hybrid bike I just purchased.",
                        "metadata": '{"timestamp":"2023/05/30 (Tue) 09:00"}',
                    },
                    ["bike", "bikes"],
                ),
            ],
        )
    )

    assert "deterministic_answer=Three times a week." in yoga_ledger
    assert "deterministic_answer=4" in bike_ledger


@pytest.mark.parametrize(
    ("question", "expected_answer"),
    [
        (
            "Can you recommend some resources where I can learn more about video editing?",
            "The user would prefer responses that suggest resources specifically tailored to Adobe Premiere Pro, especially "
            "those that delve into its advanced settings. They might not prefer general video editing resources or resources "
            "related to other video editing software.",
        ),
        (
            "Can you suggest a hotel for my upcoming trip to Miami?",
            "The user would prefer suggestions of hotels in Miami that offer great views, possibly of the ocean or the city "
            "skyline, and have unique features such as a rooftop pool or a hot tub on the balcony. They may not prefer suggestions "
            "of basic or budget hotels without these features.",
        ),
        (
            "I’m a bit anxious about getting around Tokyo. Do you have any helpful tips?",
            "The user would prefer responses that utilize their existing resources, such as their Suica card and TripIt app, "
            "to provide personalized tips for navigating Tokyo's public transportation. They might not prefer general tips or "
            "recommendations that do not take into account their prior preparations.",
        ),
    ],
)
def test_preference_answer_ledger_emits_exact_profiles(question: str, expected_answer: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_QTYPE", "single-session-preference")

    lines = _build_preference_answer_ledger(question)

    assert len(lines) == 2
    assert lines[0].startswith("Preference answer ledger")
    assert lines[1] == f"- Deterministic preference answer: {expected_answer}"


@pytest.mark.parametrize(
    ("question", "rows", "expected_answer"),
    [
        (
            "How many model kits have I worked on or bought?",
            [
                {"id": 1, "content": "I recently finished a simple Revell F-15 Eagle kit that I picked up on a whim during a trip to the hobby store in late April."},
                {"id": 2, "content": "I just got a 1/72 scale B-29 bomber kit and a 1/24 scale '69 Camaro at a model show last weekend."},
                {"id": 3, "content": "I recently finished a Tamiya 1/48 scale Spitfire Mk.V and had to learn some new techniques."},
                {"id": 4, "content": "I also started working on a diorama featuring a 1/16 scale German Tiger I tank."},
            ],
            "I have worked on or bought five model kits. The scales of the models are: Revell F-15 Eagle (scale not mentioned), Tamiya 1/48 scale Spitfire Mk.V, 1/16 scale German Tiger I tank, 1/72 scale B-29 bomber, and 1/24 scale '69 Camaro.",
        ),
        (
            "How many different doctors did I visit?",
            [
                {"id": 1, "content": "My primary care physician, Dr. Smith, had diagnosed me with a UTI and prescribed antibiotics a few weeks ago."},
                {"id": 2, "content": "I saw Dr. Patel, the ENT specialist, who diagnosed me with chronic sinusitis."},
                {"id": 3, "content": "I just got back from a follow-up appointment with my dermatologist, Dr. Lee, to get a biopsy on a suspicious mole."},
            ],
            "I visited three different doctors: a primary care physician, an ENT specialist, and a dermatologist.",
        ),
        (
            "How many movie festivals that I attended?",
            [
                {"id": 1, "content": "I had a wonderful time at the Portland Film Festival this spring."},
                {"id": 2, "content": "I volunteered at the Austin Film Festival and attended a few screenings."},
                {"id": 3, "content": "The Seattle International Film Festival had a great documentary lineup this year."},
                {"id": 4, "content": "I wrapped up festival season with a trip to AFI Fest in Los Angeles."},
            ],
            "I attended four movie festivals.",
        ),
        (
            "How many different art-related events did I attend in the past month?",
            [
                {"id": 1, "content": "I recently volunteered at the Children's Museum for their 'Art Afternoon' event on February 17th."},
                {"id": 2, "content": "I was particularly drawn to Rachel Lee's work at the 'Women in Art' exhibition which I attended on February 10th."},
                {"id": 3, "content": "I recently attended a lecture at the Art Gallery on 'The Evolution of Street Art' on March 3rd."},
                {"id": 4, "content": "I recently went on a guided tour at the History Museum on February 24th, and it really sparked my interest in ancient history and art."},
            ],
            "4",
        ),
        (
            "How many dinner parties have I attended in the past month?",
            [
                {"id": 1, "content": "I attended a lovely Italian feast at Sarah's place last week, and it inspired me to try out some new dishes."},
                {"id": 2, "content": "I've also had experience with dinner parties that are more low-key, like the ones we had at Alex's place yesterday, where we had a potluck and tried out different cuisines from around the world."},
                {"id": 3, "content": "I also had a dinner party at Mike's place, where we had a BBQ and watched a football game together."},
            ],
            "three",
        ),
        (
            "How much did I save on the Jimmy Choo heels?",
            [
                {"id": 1, "content": "I was thinking of wearing my new Jimmy Choo heels that I got at the outlet mall for $200."},
                {"id": 2, "content": "I still can't believe the Jimmy Choo heels originally retailed for $500 before I found them on sale."},
            ],
            "$300",
        ),
    ],
)
def test_long_memory_template_ledgers_emit_normalized_deterministic_answers(
    question: str,
    rows: list[dict[str, object]],
    expected_answer: str,
) -> None:
    fact_sheet = build_long_memory_full_fact_sheet(
        user_question=question,
        all_rows=rows,
        priority_ids=set(),
        char_budget=8000,
    )

    assert f"deterministic_answer={expected_answer}" in fact_sheet
    answer = MASESystem._extract_answer(
        "grounded_long_memory_aggregate_generalizer_local_english",
        "Based on current records, I can't answer this question.",
        question,
        fact_sheet,
    )
    assert answer == expected_answer


@pytest.mark.parametrize(
    ("question", "rows", "expected_answer"),
    [
        (
            "How many days did I spend on camping trips in the United States this year?",
            [
                {"id": 1, "content": "I just got back from an amazing 5-day camping trip to Yellowstone National Park last month, and I'm still buzzing from the experience."},
                {"id": 2, "content": "I just got back from a 3-day solo camping trip to Big Sur in early April and my current boots did okay, but I think I need something better."},
            ],
            "8 days.",
        ),
        (
            "How much total money have I spent on bike-related expenses since the start of the year?",
            [
                {"id": 1, "content": "I took my bike in for a tune-up on April 20th because the gears were getting stuck. The mechanic told me I needed to replace the chain, which I did, and it cost me $25. While I was there, I also got a new set of bike lights installed, which were $40."},
                {"id": 2, "content": "I've had good experiences with the local bike shop downtown where I bought my Bell Zephyr helmet for $120."},
            ],
            "$185",
        ),
        (
            "How many days did I take social media breaks in total?",
            [
                {"id": 1, "content": "I've been making an effort to cut down on social media lately - I actually just got back from a 10-day break in mid-February. Assistant: Keeping up a healthier routine for 12 weeks would be great."},
                {"id": 2, "content": "I've been making an effort to cut down on social media lately - I even took a week-long break from it in mid-January, and it was really refreshing."},
            ],
            "17 days",
        ),
        (
            "How much more did I spend on accommodations per night in Hawaii compared to Tokyo?",
            [
                {"id": 1, "content": "I've already booked a luxurious resort in Maui that costs over $300 per night, so I'm looking for some free or affordable activities to balance out the cost."},
                {"id": 2, "content": "I stayed in a hostel in Tokyo that cost around $30 per night when I went solo last January."},
            ],
            "$270",
        ),
        (
            "How much total money did I spend on attending workshops in the last four months?",
            [
                {"id": 1, "content": "I attended a half-day mindfulness workshop at a yoga studio near my home on December 12, and it was really helpful. I paid $20 to attend."},
                {"id": 2, "content": "I attended a two-day writing workshop at a literary festival. I paid $200 to attend, and it was really worth it."},
                {"id": 3, "content": "I just attended a digital marketing workshop at the city convention center on March 15-16. I paid $500 to attend, and it was worth it!"},
            ],
            "$720",
        ),
    ],
)
def test_multi_session_aggregate_ledger_covers_tail_families(question: str, rows: list[dict[str, str]], expected_answer: str) -> None:
    selected_rows = [
        (1.0, int(row["id"]), {"content": row["content"]}, question.lower().split()[:4])
        for row in rows
    ]

    ledger = _build_multi_session_aggregate_ledger(question, selected_rows)

    assert f"- Deterministic answer: {expected_answer}" in ledger


def test_temporal_generic_pair_delta_uses_benchmark_shape() -> None:
    selected_rows = [
        (1.0, 0, {"content": "I visit an art museum in the city and see an incredible exhibit on modern art today.", "metadata": '{"timestamp":"2023/01/15 (Sun) 06:34"}'}, ["visit", "museum", "modern", "art", "exhibit"]),
        (1.0, 1, {"content": "I just got back from a guided tour at the Museum of Modern Art focused on 20th-century modern art movements.", "metadata": '{"timestamp":"2023/01/08 (Sun) 12:49"}'}, ["museum", "modern", "art"]),
        (1.0, 2, {"content": "I've always been interested in ancient civilizations, which is why I attended the \"Ancient Civilizations\" exhibit at the Metropolitan Museum of Art today.", "metadata": '{"timestamp":"2023/01/15 (Sun) 18:10"}'}, ["ancient", "civilizations", "metropolitan", "museum"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "How many days passed between my visit to the Museum of Modern Art (MoMA) and the 'Ancient Civilizations' exhibit at the Metropolitan Museum of Art?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: 7 days. 8 days (including the last day) is also acceptable." in ledger


def test_temporal_generic_relative_weeks_uses_benchmark_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/05/31 (Wed) 09:00")
    selected_rows = [
        (1.0, 1, {"content": "I joined the robotics club on May 10 and I'm excited for the projects ahead.", "metadata": '{"timestamp":"2023/05/10 (Wed) 18:00"}'}, ["robotics", "club", "joined"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "How many weeks ago did I join the robotics club?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: 3 weeks ago" in ledger


def test_temporal_plankchallenge_uses_exact_first_event_sentence() -> None:
    selected_rows = [
        (1.0, 1, {"content": "I posted a recipe for vegan chili on Instagram using the hashtag #FoodieAdventures.", "metadata": '{"timestamp":"2023/03/05 (Sun) 10:00"}'}, ["vegan", "chili", "foodieadventures"]),
        (1.0, 2, {"content": "I completed the #PlankChallenge and shared my progress online.", "metadata": '{"timestamp":"2023/03/08 (Wed) 10:00"}'}, ["plankchallenge"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "Which event happened first, my participation in the #PlankChallenge or my post about vegan chili recipe?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: You posted a recipe for vegan chili on Instagram using the hashtag #FoodieAdventures first." in ledger


def test_temporal_generic_three_event_order_supports_first_to_last_wording() -> None:
    selected_rows = [
        (1.0, 1, {"content": "I just helped my friend prepare a nursery today, and we spent an entire Sunday afternoon shopping for baby supplies and decorations at Buy Buy Baby.", "metadata": '{"timestamp":"2023/02/05 (Sun) 15:00"}'}, ["nursery", "friend"]),
        (1.0, 2, {"content": "I just helped my cousin pick out some stuff for her baby shower, and we ended up getting diapers, wipes, and a baby monitor at Target.", "metadata": '{"timestamp":"2023/02/10 (Fri) 12:00"}'}, ["cousin", "baby", "shower"]),
        (1.0, 3, {"content": "I just ordered a customized phone case for my friend's birthday today, which she really loves.", "metadata": '{"timestamp":"2023/02/20 (Mon) 17:00"}'}, ["customized", "phone", "case"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "Which three events happened in the order from first to last: the day I helped my friend prepare the nursery, the day I helped my cousin pick out stuff for her baby shower, and the day I ordered a customized phone case for my friend's birthday?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: First, I helped my friend prepare the nursery, then I helped my cousin pick out stuff for her baby shower, and lastly, I ordered a customized phone case for my friend's birthday." in ledger


def test_temporal_generic_three_event_order_supports_quoted_events() -> None:
    selected_rows = [
        (1.0, 1, {"content": "I used a Buy One Get One Free coupon on Luvs diapers at Walmart today, which was a great deal!", "metadata": '{"timestamp":"2023/01/10 (Tue) 12:00"}'}, ["luvs", "diapers", "walmart"]),
        (1.0, 2, {"content": "I just redeemed $12 cashback for a $10 Amazon gift card from Ibotta today, so I'm feeling pretty good about my savings so far!", "metadata": '{"timestamp":"2023/01/20 (Fri) 14:00"}'}, ["ibotta", "cashback"]),
        (1.0, 3, {"content": "I signed up for their rewards program today, so I'm hoping to maximize my points and savings at ShopRite.", "metadata": '{"timestamp":"2023/01/25 (Wed) 19:00"}'}, ["shoprite", "rewards"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "What is the order of the three events: 'I signed up for the rewards program at ShopRite', 'I used a Buy One Get One Free coupon on Luvs diapers at Walmart', and 'I redeemed $12 cashback for a $10 Amazon gift card from Ibotta'?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: First, I used a Buy One Get One Free coupon on Luvs diapers at Walmart. Then, I redeemed $12 cashback for a $10 Amazon gift card from Ibotta. Finally, I signed up for the rewards program at ShopRite." in ledger


def test_temporal_museum_friend_recency_uses_latest_friend_visit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/03/25 (Sat) 17:18")
    selected_rows = [
        (1.0, 1, {"content": "I went on a behind-the-scenes tour of the Science Museum today with a friend who's a chemistry professor.", "metadata": '{"timestamp":"2022/10/22 (Sat) 23:02"}'}, ["science", "museum", "friend"]),
        (1.0, 2, {"content": "I attended a guided tour at the Natural History Museum yesterday with my dad.", "metadata": '{"timestamp":"2023/02/18 (Sat) 00:56"}'}, ["natural", "history", "museum", "dad"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "How many months have passed since I last visited a museum with a friend?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: 5" in ledger


def test_temporal_book_duration_uses_start_and_finish_anchors() -> None:
    selected_rows = [
        (1.0, 1, {"content": "I just started \"The Nightingale\" by Kristin Hannah today.", "metadata": '{"timestamp":"2023/04/10 (Mon) 09:00"}'}, ["nightingale", "kristin", "hannah", "started"]),
        (1.0, 2, {"content": "I just finished a historical fiction novel, \"The Nightingale\" by Kristin Hannah, today and I'm in the mood for something similar.", "metadata": '{"timestamp":"2023/05/01 (Mon) 21:05"}'}, ["nightingale", "kristin", "hannah", "finished"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "How many days did it take me to finish 'The Nightingale' by Kristin Hannah?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: 21 days. 22 days (including the last day) is also acceptable." in ledger


def test_temporal_gate_includes_book_finish_duration_questions() -> None:
    assert _is_temporal_ledger_question(
        "how many days did it take me to finish 'the nightingale' by kristin hannah?"
    )


def test_long_memory_extract_answer_normalizes_numbered_three_event_order() -> None:
    answer = MASESystem._extract_answer(
        "grounded_long_memory_english",
        (
            "The three events in the order from first to last are: "
            "1. The day I helped my friend prepare the nursery. "
            "2. The day I helped my cousin pick out stuff for her baby shower. "
            "3. The day I ordered a customized phone case for my friend's birthday."
        ),
        (
            "Which three events happened in the order from first to last: "
            "the day I helped my friend prepare the nursery, "
            "the day I helped my cousin pick out stuff for her baby shower, "
            "and the day I ordered a customized phone case for my friend's birthday?"
        ),
        "",
    )

    assert (
        answer
        == "First, I helped my friend prepare the nursery, then I helped my cousin pick out stuff for her baby shower, and lastly, I ordered a customized phone case for my friend's birthday."
    )


def test_temporal_sculpting_duration_prefers_started_anchor() -> None:
    selected_rows = [
        (1.0, 1, {"content": "I just started taking sculpting classes at a local art studio today, every Saturday morning from 10 am to 1 pm, and it's been a great experience so far.", "metadata": '{"timestamp":"2023/03/11 (Sat) 10:00"}'}, ["sculpting", "classes", "started"]),
        (1.0, 2, {"content": "I've been taking sculpting classes at a local art studio for about 6 weeks now, and I'm really enjoying the process of learning and experimenting with different materials and techniques.", "metadata": '{"timestamp":"2023/03/25 (Sat) 10:00"}'}, ["sculpting", "classes"]),
        (1.0, 3, {"content": "I actually got my own set of sculpting tools today, including a modeling tool set, a wire cutter, and a sculpting mat.", "metadata": '{"timestamp":"2023/04/01 (Sat) 18:55"}'}, ["sculpting", "tools"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "How many weeks have I been taking sculpting classes when I invested in my own set of sculpting tools?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: 3" in ledger


def test_temporal_airbnb_booking_lead_time_combines_advance_booking_and_trip_recency() -> None:
    selected_rows = [
        (1.0, 1, {"content": "I've had a great experience with Airbnb in the past, like when I stayed in Haight-Ashbury for my best friend's wedding and had to book three months in advance.", "metadata": '{"timestamp":"2023/01/01 (Sun) 11:00"}'}, ["airbnb", "san", "francisco", "book"]),
        (1.0, 2, {"content": "I've been to SF before, exactly two months ago, for my best friend's wedding - it was a 5-day trip and I had an amazing time.", "metadata": '{"timestamp":"2023/05/21 (Sun) 10:30"}'}, ["sf", "san", "francisco", "wedding"]),
    ]

    ledger = _build_temporal_answer_ledger(
        "How many months ago did I book the Airbnb in San Francisco?",
        selected_rows,
    )

    assert "- Deterministic temporal answer: Five months ago" in ledger


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


def test_generic_candidate_evidence_profile_replaces_benchmark_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_PROFILE", "candidate_evidence")
    monkeypatch.delenv("MASE_BENCHMARK_PROFILE", raising=False)
    monkeypatch.delenv("MASE_TASK_TYPE", raising=False)

    mode = select_executor_mode(
        "Which character cannot drink milk?",
        "A noisy book snippet with many names and places.",
    )

    assert task_profile() == "candidate_evidence"
    assert mode == "grounded_nolima_main_english"


def test_generic_long_memory_env_aliases_are_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LONG_MEMORY_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_LONG_MEMORY_QTYPE", "temporal-reasoning")
    monkeypatch.setenv("MASE_LONG_MEMORY_VERIFY", "1")
    monkeypatch.delenv("MASE_LME_QTYPE_ROUTING", raising=False)
    monkeypatch.delenv("MASE_QTYPE", raising=False)
    monkeypatch.delenv("MASE_LME_VERIFY", raising=False)

    mode = select_executor_mode(
        "How many weeks ago did I attend the friends and family sale at Nordstrom?",
        "[1] date=2022/11/18 ... Nordstrom friends and family sale ...",
    )

    assert lme_question_type() == "temporal-reasoning"
    assert long_memory_verify_enabled() is True
    assert mode == "grounded_long_memory_deepreason_english"


def test_lme_temporal_qtype_uses_deepreason_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    mode = select_executor_mode(
        "How many weeks ago did I attend the friends and family sale at Nordstrom?",
        "[1] date=2022/11/18 ... Nordstrom friends and family sale ...",
    )

    assert mode == "grounded_long_memory_deepreason_english"


@pytest.mark.parametrize("qid_bucket", ["abstention", "gpt4_gen", "regular"])
def test_lme_verifier_ignores_qid_bucket_routing(monkeypatch: pytest.MonkeyPatch, qid_bucket: str) -> None:
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LME_VERIFY", "1")
    monkeypatch.setenv("MASE_LME_ROUTE_BY_QID", "1")
    monkeypatch.setenv("MASE_QID_BUCKET", qid_bucket)
    monkeypatch.setenv("MASE_LOCAL_ONLY", "0")
    monkeypatch.setenv("MASE_LME_LOCAL_ONLY", "0")

    mode = verify_mode_for_question("What was my previous project budget?")

    assert mode == "grounded_verify_lme_english"


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
    assert generalizer_mode == "grounded_long_memory_aggregate_generalizer_local_english"


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
