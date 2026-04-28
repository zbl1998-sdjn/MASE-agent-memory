from __future__ import annotations

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
from mase.mode_selector import (
    generalizer_mode_for_question,
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
