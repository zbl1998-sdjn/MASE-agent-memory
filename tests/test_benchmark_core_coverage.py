from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks import adapters, registry, runner, scoring
from benchmarks.schemas import BenchmarkSample, BenchmarkTurn


def test_dataset_provenance_hashes_sensitive_sample_fields() -> None:
    sample = BenchmarkSample(
        id="synthetic-secret-case",
        benchmark="synthetic",
        task_type="qa",
        question="Which relay station did the operator choose?",
        ground_truth="relay-seven-secret",
        history=[BenchmarkTurn(role="user", content="Remember relay-seven-secret.")],
        context="private context",
        metadata={"dataset": "holdout", "length": "short", "irrelevant": "not exported"},
    )

    provenance = runner._build_dataset_provenance(
        "synthetic",
        [sample],
        path=None,
        config="holdout",
        split="test",
    )
    serialized = json.dumps(provenance, ensure_ascii=False, sort_keys=True)

    assert provenance["source"] == "hf-default"
    assert provenance["sample_count"] == 1
    assert provenance["task_type_counts"] == {"qa": 1}
    assert provenance["sample_ids_sha256"]
    assert provenance["sample_payload_sha256"]
    assert "relay-seven-secret" not in serialized
    assert "Which relay" not in serialized
    assert provenance["sample_payload_sha256"] != runner._build_dataset_provenance(
        "synthetic",
        [BenchmarkSample(id="synthetic-secret-case", benchmark="synthetic", task_type="qa", question="q", ground_truth="x")],
        path=None,
        config="holdout",
        split="test",
    )["sample_payload_sha256"]


def test_runner_text_hashing_chunking_and_error_classification() -> None:
    assert runner._hash_text("same") == runner._hash_text("same")
    assert runner._hash_json({"b": 2, "a": 1}) == runner._hash_json({"a": 1, "b": 2})
    assert runner._classify_error_kind("ConnectionError: timed out") == "infra_error"
    assert runner._classify_error_kind("baseline_skipped") == "skipped"
    assert runner._classify_error_kind("ValueError: bad sample") == "execution_error"
    assert runner._classify_error_kind("") is None

    chunks = runner._chunk_context("First paragraph.\n\n" + ("word " * 40), max_chars=35)
    assert len(chunks) > 1
    assert all(len(chunk) <= 35 for chunk in chunks)
    assert runner._benchmark_history_summary("The relay changed to Juniper-7 after the final dispatch.") == (
        "The relay changed to Juniper-7 after the final dispatch."
    )


def test_runner_aggregates_call_log_and_scoreboard() -> None:
    call_summary = runner._aggregate_call_log(
        [
            {"agent_type": "router", "elapsed_seconds": 0.111111, "usage": {"prompt_tokens": 2}},
            {"agent_type": "router", "elapsed_seconds": 0.222222, "usage": {"completion_tokens": 3}},
            {"agent_type": "executor", "elapsed_seconds": 1.0, "usage": None},
        ]
    )
    assert call_summary["call_count"] == 3
    assert call_summary["by_agent"]["router"]["call_count"] == 2
    assert call_summary["by_agent"]["router"]["usage_totals"] == {"prompt_tokens": 2.0, "completion_tokens": 3.0}

    br = runner.BenchmarkRunner(baseline_profile="disabled", sample_retry_count=0)
    scoreboard = br._build_scoreboard(
        [
            {
                "mase": {
                    "score": {"all_matched": True, "score": 1.0},
                    "metrics": {"wall_clock_seconds": 2.0, "usage_totals": {"prompt_tokens": 4}},
                    "data_gap_audit": {"status": "ok"},
                    "completed": True,
                },
                "baseline": {
                    "score": {"all_matched": False, "score": 0.0},
                    "metrics": {"elapsed_seconds": 1.0, "usage": {"prompt_tokens": 1}},
                    "error_kind": "infra_error",
                    "completed": False,
                },
            },
            {
                "mase": {
                    "score": {"all_matched": False, "score": 0.0},
                    "metrics": {"wall_clock_seconds": 4.0},
                    "data_gap_audit": {"status": "data_gap"},
                    "error_kind": "execution_error",
                    "completed": False,
                },
                "baseline": {"score": {"all_matched": True, "score": 1.0}, "metrics": {"elapsed_seconds": 3.0}, "completed": True},
            },
        ]
    )

    assert br._baseline_enabled() is False
    assert scoreboard["mase_pass_count"] == 1
    assert scoreboard["mase_adjusted_pass_count"] == 2
    assert scoreboard["mase_data_gap_count"] == 1
    assert scoreboard["baseline_infra_error_count"] == 1
    assert scoreboard["mase_avg_wall_clock_seconds"] == 3.0


def test_run_benchmark_empty_suite_writes_summary_without_resolving_profile_late(monkeypatch, tmp_path: Path) -> None:
    state = {"loaded": False}

    def fake_load_samples(*args, **kwargs) -> list[BenchmarkSample]:
        state["loaded"] = True
        return []

    def fake_resolve_config_path() -> Path:
        if state["loaded"]:
            return runner.BASE_DIR / "config.other.json"
        return runner.BASE_DIR / "config.json"

    monkeypatch.setattr(runner, "_load_config_profiles", lambda: {"published": {"path": "config.json"}})
    monkeypatch.setattr(runner, "_load_benchmark_fallbacks", lambda: {})
    monkeypatch.setattr(runner, "load_benchmark_samples", fake_load_samples)
    monkeypatch.setattr(runner, "resolve_config_path", fake_resolve_config_path)
    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(runner, "MEMORY_RUNS_DIR", tmp_path / "memory_runs")

    summary = runner.BenchmarkRunner(baseline_profile="disabled").run_benchmark("synthetic")

    assert summary["completed"] is True
    assert summary["sample_count"] == 0
    assert summary["config_profile"] == "published"
    assert Path(summary["results_path"]).exists()


def test_ingest_turns_and_context_use_hashed_sample_metadata() -> None:
    class FakeNotetaker:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []

        def write(self, **kwargs) -> None:
            self.rows.append(kwargs)

    class FakeSystem:
        def __init__(self) -> None:
            self.notetaker_agent = FakeNotetaker()

    system = FakeSystem()
    runner._ingest_turns_into_mase(
        system,  # type: ignore[arg-type]
        [
            BenchmarkTurn(role="user", content="Remember that Juniper-7 is active.", timestamp="2024-01-01", session_id="s1"),
            BenchmarkTurn(role="assistant", content="Noted."),
            BenchmarkTurn(role="user", content="Alder-4 is retired."),
        ],
        benchmark_question_id="raw-sensitive-id",
    )
    runner._ingest_context_into_mase(system, "Dispatch paragraph one.\n\nDispatch paragraph two.")

    assert len(system.notetaker_agent.rows) >= 3
    metadata = system.notetaker_agent.rows[0]["metadata"]
    assert metadata["benchmark_id_visibility"] == "hashed"
    assert metadata["benchmark_sample_hash"] == runner._hash_text("raw-sensitive-id")
    assert "raw-sensitive-id" not in json.dumps(metadata, ensure_ascii=False)
    assert system.notetaker_agent.rows[0]["assistant_response"] == "Noted."
    assert system.notetaker_agent.rows[1]["metadata"]["source"] == "benchmark_history_incomplete"
    assert any(row["metadata"]["source"] == "benchmark_context" for row in system.notetaker_agent.rows)


def test_registry_loads_local_records_and_smoke_samples(tmp_path: Path) -> None:
    json_path = tmp_path / "records.json"
    json_path.write_text(json.dumps({"data": [{"id": "one"}, {"id": "two"}]}), encoding="utf-8")
    jsonl_path = tmp_path / "records.jsonl"
    jsonl_path.write_text('{"id": "three"}\n\n{"id": "four"}\n', encoding="utf-8")

    assert registry._load_local_records(str(json_path)) == [{"id": "one"}, {"id": "two"}]
    assert registry._load_local_records(str(jsonl_path)) == [{"id": "three"}, {"id": "four"}]
    (tmp_path / "records.txt").write_text("unsupported", encoding="utf-8")
    with pytest.raises(ValueError):
        registry._load_local_records(str(tmp_path / "records.txt"))
    with pytest.raises(FileNotFoundError):
        registry._load_local_records(str(tmp_path / "missing.json"))

    assert "generalization_smoke" in registry.list_benchmarks()
    samples = registry.load_benchmark_samples("generalization_smoke", sample_limit=1)
    assert len(samples) == 1
    with pytest.raises(KeyError):
        registry.load_benchmark_samples("unknown")


def test_adapters_parse_common_benchmark_records() -> None:
    turns = adapters._parse_history_text("User: remember relay\nAssistant: noted\nUser: what relay?")
    assert [turn.role for turn in turns] == ["user", "assistant", "user"]
    session_turns = adapters._parse_history_text(
        "History Chats:Session alpha:\n[{'role': 'user', 'content': 'hello'}]"
    )
    assert session_turns[0].session_id == "alpha"

    longmem = adapters.adapt_longmemeval_record(
        {
            "custom_id": "lm-1",
            "question": "Which relay?",
            "answer": "Juniper-7",
            "focused_input": "User: Juniper-7 is active.",
            "question_type": "single-session-user",
        },
        "longmemeval_s",
    )
    assert longmem.task_type == "long_memory"
    assert longmem.answer_keywords == ["Juniper-7"]
    assert longmem.metadata["history_shape"] == "focused_input"

    lveval = adapters.adapt_lveval_record(
        {"id": "lv-1", "question": "Port?", "answers": ["9912"], "answer_keywords": "9912; gateway"},
        "lveval",
    )
    assert lveval.task_type == "long_context_qa"
    assert lveval.answer_keywords == ["9912", "gateway"]

    mmlu = adapters.adapt_mmlu_record({"question": "Best?", "choices": ["bad", "good"], "answer": "B"}, "mmlu")
    assert "B. good" in mmlu.question
    assert mmlu.metadata["correct_option_text"] == "B. good"

    gpqa = adapters.adapt_gpqa_record({"Question": "Best?", "Correct Answer": "yes", "Incorrect Answer 1": "no"}, "gpqa")
    assert gpqa.ground_truth == "A"
    assert gpqa.options[0] == "A. yes"

    gsm8k = adapters.adapt_gsm8k_record({"question": "1+1?", "answer": "Reasoning\n#### 2"}, "gsm8k")
    assert gsm8k.ground_truth == "2"

    humaneval = adapters.adapt_humaneval_record({"prompt": "def add", "entry_point": "add"}, "humaneval")
    assert humaneval.entry_point == "add"


def test_scoring_handles_choice_math_code_long_context_and_phrase_variants() -> None:
    mc = BenchmarkSample(
        id="mc",
        benchmark="mmlu",
        task_type="multiple_choice",
        question="Choose",
        ground_truth="B",
        metadata={"correct_option_text": "correct option"},
    )
    assert scoring.score_sample(mc, "Final answer: B")["all_matched"] is True
    assert scoring.score_sample(mc, "The correct option is present.")["all_matched"] is True

    math = BenchmarkSample(id="math", benchmark="gsm8k", task_type="math", question="calc", ground_truth="61")
    assert scoring.score_sample(math, "The total is 61.")["all_matched"] is True

    code = BenchmarkSample(
        id="code",
        benchmark="humaneval",
        task_type="code_generation",
        question="write add",
        ground_truth="",
        answer_keywords=["return a + b"],
        entry_point="add",
    )
    assert scoring.score_sample(code, "def add(a, b):\n    return a + b")["all_matched"] is True

    long_context = BenchmarkSample(
        id="lc",
        benchmark="longbench",
        task_type="long_context_qa",
        question="choose",
        ground_truth="C",
        metadata={"mc_letter": "C", "correct_option_text": "third option"},
    )
    assert scoring.score_sample(long_context, "Answer: C")["details"]["expected"] == "C"

    qa = BenchmarkSample(
        id="qa",
        benchmark="synthetic",
        task_type="qa",
        question="How many?",
        ground_truth="four bikes (or 4 bikes)",
    )
    assert scoring.score_sample(qa, "I have 4 bikes.")["all_matched"] is True
