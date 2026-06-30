from __future__ import annotations

import pytest

from mase import mode_selector
from mase.reasoning_engine import (
    ReasoningWorkspace,
    _classify_operation,
    _dedupe_strings,
    _extract_deterministic_answer,
    _extract_focus_entities,
    _extract_target_unit,
    build_reasoning_workspace,
)


_MODE_ENV_KEYS = (
    "MASE_TASK_TYPE",
    "MASE_LVEVAL_DATASET",
    "MASE_LONG_CONTEXT_VARIANT",
    "MASE_LOCAL_ONLY",
    "MASE_LONG_MEMORY_LOCAL_ONLY",
    "MASE_LME_LOCAL_ONLY",
    "MASE_LONG_MEMORY_TEMPORAL_DEEPREASON",
    "MASE_LME_TEMPORAL_DEEPREASON",
    "MASE_LONG_MEMORY_QTYPE_ROUTING",
    "MASE_LME_QTYPE_ROUTING",
    "MASE_LONG_MEMORY_QTYPE",
    "MASE_QTYPE",
    "MASE_LONG_MEMORY_RETRY",
    "MASE_LME_RETRY",
    "MASE_LONG_MEMORY_VERIFY",
    "MASE_LME_VERIFY",
    "MASE_TASK_PROFILE",
    "MASE_BENCHMARK_PROFILE",
)


def _clear_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _MODE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_reasoning_workspace_serializes_optional_fields_and_unknowns() -> None:
    workspace = ReasoningWorkspace(
        operation="lookup",
        focus_entities=["Alpha", "Beta"],
        target_unit="days",
        sub_tasks=["retrieve", "answer"],
        verification_focus=["exact"],
        deterministic_answer="42",
        evidence_confidence="",
        verifier_action="",
        followup_needed=True,
    )

    assert workspace.to_dict()["focus_entities"] == ["Alpha", "Beta"]
    text = workspace.to_text()
    assert "- target_unit=days" in text
    assert "- deterministic_answer=42" in text
    assert "- evidence_confidence=unknown" in text
    assert "- followup_needed=yes" in text


def test_reasoning_helpers_cover_classification_focus_and_answer_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _dedupe_strings([" Alpha ", "", "alpha", "Beta"]) == ["Alpha", "Beta"]

    monkeypatch.setenv("MASE_QTYPE", "knowledge-update")
    assert _classify_operation("What role did I mention?") == "update"
    monkeypatch.delenv("MASE_QTYPE", raising=False)

    cases = {
        "How much more did the room cost?": "difference",
        "How long was the trip?": "duration",
        "How much did I spend?": "money",
        "How many books in total?": "count",
        "What happened before dinner?": "chronology",
        "Which scientist was named?": "disambiguation",
        "Tell me the relay code.": "lookup",
    }
    for question, expected in cases.items():
        assert _classify_operation(question) == expected

    assert _extract_target_unit("How much did it cost?") == "$"
    assert _extract_target_unit("How many days did it take?") == "days"
    assert _extract_focus_entities("") == []
    assert "Project Atlas" in _extract_focus_entities('Which "Project Atlas" milestone did Alice Brown mention?')
    assert _extract_focus_entities("项目节点是什么时候确认的？") == ["项目节点是什么时候确认的"]
    assert _extract_deterministic_answer("Deterministic money total: $12 | source rows") == "$12"
    assert _extract_deterministic_answer("Deterministic answer: Alpha (from row 3)") == "Alpha"


def test_build_reasoning_workspace_uses_defaults_and_deterministic_answer() -> None:
    workspace = build_reasoning_workspace(
        "How many total items were on the rotation table list?",
        "evidence_confidence=high\nverifier_action=verify",
    )
    assert workspace.operation == "count"
    assert workspace.followup_needed is True
    assert "table/list wording completeness" in workspace.verification_focus
    assert "aggregation completeness" in workspace.verification_focus

    deterministic = build_reasoning_workspace(
        "Who was named?",
        "verifier_action=verify\nDeterministic answer: Alice.",
        planner_sub_tasks=["custom", "custom", ""],
        planner_verification_focus=["name completeness"],
    )
    assert deterministic.deterministic_answer == "Alice."
    assert deterministic.sub_tasks == ["custom"]
    assert deterministic.followup_needed is False


def test_long_context_mode_selector_covers_length_and_dataset_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("MASE_LVEVAL_DATASET", "unknown_12k")
    assert mode_selector.long_context_length_bucket() == ""
    assert mode_selector.long_context_search_limit(default=7) == 7
    assert mode_selector.long_context_window_radius(default=111) == 111

    monkeypatch.setenv("MASE_LVEVAL_DATASET", "factrecall_en_64k")
    assert mode_selector.long_context_length_bucket() == "64k"
    assert mode_selector.long_context_search_limit() == 20
    assert mode_selector.long_context_window_radius() == 320

    monkeypatch.setenv("MASE_TASK_TYPE", "long_context_qa")
    monkeypatch.setenv("MASE_LVEVAL_DATASET", "multi_doc_en_32k")
    assert mode_selector.is_multidoc_long_context() is True
    assert mode_selector.select_executor_mode("Which document supports Alice?", "candidate facts") == (
        "grounded_long_context_multidoc_english"
    )
    monkeypatch.setenv("MASE_LONG_CONTEXT_VARIANT", "mc")
    assert mode_selector.select_executor_mode("Which option is correct?", "candidate facts") == "grounded_long_context_mc"
    monkeypatch.delenv("MASE_LONG_CONTEXT_VARIANT", raising=False)
    monkeypatch.setenv("MASE_LVEVAL_DATASET", "factrecall_zh_32k")
    assert mode_selector.is_factrecall_long_context() is True
    assert mode_selector.select_executor_mode("这个事实是什么？", "候选事实") == "grounded_long_context"
    assert mode_selector.select_executor_mode("What now?", "") == "general_answer_reasoning"


def test_long_memory_mode_selector_covers_local_retry_verifier_and_generalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LOCAL_ONLY", "1")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_QTYPE", "temporal-reasoning")

    assert mode_selector.select_executor_mode("How many days ago did I start?", "facts") == (
        "grounded_long_memory_english"
    )
    monkeypatch.setenv("MASE_LME_TEMPORAL_DEEPREASON", "1")
    assert mode_selector.select_executor_mode("How many days ago did I start?", "facts") == (
        "grounded_long_memory_deepreason_english"
    )

    monkeypatch.delenv("MASE_LOCAL_ONLY", raising=False)
    monkeypatch.delenv("MASE_LME_TEMPORAL_DEEPREASON", raising=False)
    monkeypatch.setenv("MASE_LME_RETRY", "1")
    assert mode_selector.select_executor_mode("How many days ago did I start?", "facts") == "grounded_long_memory_retry_kimi"

    monkeypatch.delenv("MASE_LME_RETRY", raising=False)
    monkeypatch.setenv("MASE_LME_VERIFY", "1")
    assert mode_selector.verify_mode_for_question("这个答案对吗？") == "grounded_verify_lme"

    monkeypatch.setenv("MASE_LOCAL_ONLY", "1")
    monkeypatch.setenv("MASE_QTYPE", "single-session-preference")
    assert mode_selector.generalizer_mode_for_question("我更喜欢哪个？") == "grounded_answer"
    monkeypatch.setenv("MASE_QTYPE", "multi-session")
    assert mode_selector.generalizer_mode_for_question("总共多少次？") == "grounded_analysis_reasoning"


@pytest.mark.parametrize(
    ("question", "fact_sheet", "expected"),
    [
        ("How many items are in total?", "facts", "grounded_analysis_english_reasoning"),
        ("Which candidate is correct?", "candidate row", "grounded_disambiguation_english_reasoning"),
        ("Tell me the note.", "facts", "grounded_answer_english_reasoning"),
        ("请分析总共多少钱？", "事实", "grounded_analysis_reasoning"),
        ("哪个候选正确？", "候选裁决表", "grounded_disambiguation_reasoning"),
        ("普通问题？", "事实", "grounded_answer"),
    ],
)
def test_executor_mode_generic_language_branches(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    fact_sheet: str,
    expected: str,
) -> None:
    _clear_mode_env(monkeypatch)
    assert mode_selector.select_executor_mode(question, fact_sheet) == expected


def test_verify_and_generalizer_cover_context_and_cloud_qtype_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("MASE_TASK_TYPE", "long_context_qa")
    assert mode_selector.verify_mode_for_question("这个证据对吗？") == "grounded_verify_long_context"

    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("MASE_TASK_TYPE", "long_memory")
    monkeypatch.setenv("MASE_LONG_MEMORY_QTYPE_ROUTING", "1")
    monkeypatch.setenv("MASE_LONG_MEMORY_QTYPE", "single-session-preference")
    assert mode_selector.generalizer_mode_for_question("What did I prefer?") == (
        "grounded_long_memory_preference_generalizer_english"
    )
    monkeypatch.setenv("MASE_LONG_MEMORY_QTYPE", "multi-session")
    assert mode_selector.generalizer_mode_for_question("What happened in total?") == (
        "grounded_long_memory_aggregate_generalizer_english"
    )
    assert mode_selector.generalizer_mode_for_question("总共多少？") == "grounded_answer"
