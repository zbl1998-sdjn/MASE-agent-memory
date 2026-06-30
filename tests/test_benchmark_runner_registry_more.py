from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest

from benchmarks import registry, runner
from benchmarks.schemas import BenchmarkSample, BenchmarkTurn


def test_registry_lveval_local_zip_dir_jsonl_and_errors(tmp_path: Path) -> None:
    assert registry._iter_lveval_config_names()[0].endswith("_16k")
    assert registry._split_lveval_config("factrecall_zh_256k") == ("factrecall_zh", "256k")
    with pytest.raises(ValueError):
        registry._split_lveval_config("bad_config")

    zip_path = tmp_path / "lveval.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "factrecall_zh/factrecall_zh_16k.jsonl",
            '{"id":"one","question":"q","answers":["a"]}\n{"id":"one","question":"dup","answers":["a"]}\n',
        )
    records = registry._load_lveval_records(str(zip_path), "factrecall_zh_16k", sample_limit=5)
    assert [record["id"] for record in records] == ["one"]
    with pytest.raises(ValueError):
        registry._load_lveval_records(str(zip_path), None, sample_limit=1)

    data_dir = tmp_path / "lveval_dir"
    task_dir = data_dir / "factrecall_zh"
    task_dir.mkdir(parents=True)
    (task_dir / "factrecall_zh_16k.jsonl").write_text(
        '{"id":"dir-one","question":"q","answers":["a"]}\n',
        encoding="utf-8",
    )
    dir_records = registry._load_lveval_records(str(data_dir), "factrecall_zh_16k", sample_limit=1)
    assert dir_records[0]["id"] == "dir-one"

    jsonl_path = tmp_path / "single.jsonl"
    jsonl_path.write_text('{"id":"jsonl-one","question":"q","answers":["a"]}\n', encoding="utf-8")
    assert registry._load_lveval_records(str(jsonl_path), "factrecall_zh_16k", sample_limit=1)[0]["id"] == "jsonl-one"

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        registry._load_lveval_records(str(empty_dir), "factrecall_zh_16k", sample_limit=1)
    (tmp_path / "records.txt").write_text("unsupported", encoding="utf-8")
    with pytest.raises(ValueError):
        registry._load_lveval_records(str(tmp_path / "records.txt"), "factrecall_zh_16k", sample_limit=1)


def test_registry_hf_and_adapter_loaders(monkeypatch, tmp_path: Path) -> None:
    class FakeDataset:
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self.rows = rows

        def __len__(self) -> int:
            return len(self.rows)

        def __iter__(self):
            return iter(self.rows)

        def select(self, indices) -> FakeDataset:
            return FakeDataset([self.rows[index] for index in indices])

    observed: dict[str, Any] = {}

    def fake_load_dataset(path: str, config: str | None, split: str) -> FakeDataset:
        observed.update({"path": path, "config": config, "split": split})
        return FakeDataset([{"id": "one"}, {"id": "two"}])

    monkeypatch.setattr(registry, "load_dataset", fake_load_dataset)
    samples = registry._load_hf_samples(
        name="synthetic",
        path="repo/dataset",
        config="cfg",
        split=None,
        sample_limit=1,
        adapter=lambda record, name: BenchmarkSample(
            id=record["id"],
            benchmark=name,
            task_type="qa",
            question="q",
            ground_truth="a",
        ),
    )
    assert [sample.id for sample in samples] == ["one"]
    assert observed == {"path": "repo/dataset", "config": "cfg", "split": "test"}

    local_path = tmp_path / "records.json"
    local_path.write_text('[{"id":"local"}]', encoding="utf-8")
    local_samples = registry._load_with_adapter(
        "synthetic",
        lambda record, name: BenchmarkSample(id=record["id"], benchmark=name, task_type="qa", question="q", ground_truth="a"),
        str(local_path),
        "hf/path",
        None,
        None,
        1,
    )
    assert local_samples[0].id == "local"

    monkeypatch.setattr(
        registry,
        "_load_hf_samples",
        lambda **kwargs: [BenchmarkSample(id="hf", benchmark=kwargs["name"], task_type="qa", question="q", ground_truth="a")],
    )
    hf_samples = registry._load_with_adapter(
        "synthetic",
        lambda record, name: BenchmarkSample(id="unused", benchmark=name, task_type="qa", question="q", ground_truth="a"),
        str(tmp_path / "missing.json"),
        "hf/path",
        "cfg",
        "train",
        None,
    )
    assert hf_samples[0].id == "hf"


def test_registry_longbench_and_lveval_public_loaders(monkeypatch, tmp_path: Path) -> None:
    longbench_path = tmp_path / "longbench.json"
    longbench_path.write_text(
        json.dumps(
            [
                {
                    "_id": "short",
                    "question": "q1",
                    "choice_A": "yes",
                    "choice_B": "no",
                    "answer": "A",
                    "length": "short",
                    "context": "ctx",
                },
                {
                    "_id": "long",
                    "question": "q2",
                    "choice_A": "yes",
                    "choice_B": "no",
                    "answer": "B",
                    "length": "long",
                    "context": "ctx",
                },
            ]
        ),
        encoding="utf-8",
    )
    samples = registry._load_longbench_v2("longbench_v2", path=str(longbench_path), config="long", sample_limit=None)
    assert [sample.id for sample in samples] == ["long"]
    assert samples[0].metadata["mc_letter"] == "B"

    monkeypatch.setattr(registry, "hf_hub_download", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        registry._load_longbench_v2("longbench_v2", path=None, config=None, sample_limit=1)

    monkeypatch.setattr(
        registry,
        "_load_lveval_records",
        lambda path, config, sample_limit: [
            {"id": "same", "question": "q", "answers": ["a"]},
            {"id": "same", "question": "duplicate", "answers": ["a"]},
            {"id": "other", "question": "q", "answers": ["b"]},
        ],
    )
    lveval_samples = registry._load_lveval("lveval", sample_limit=2)
    assert [sample.id for sample in lveval_samples] == ["same", "other"]


def test_runner_config_shape_helpers_and_progress(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(runner, "BASE_DIR", tmp_path)
    assert runner._load_config_profiles() == {}
    (tmp_path / "config.profiles.json").write_text(
        json.dumps({"profiles": {"published": {"path": "config.json"}}}),
        encoding="utf-8",
    )
    assert runner._load_config_profiles() == {"published": {"path": "config.json"}}
    assert runner._resolve_config_profile_name(tmp_path / "config.json", {"published": {"path": "config.json"}}) == "published"
    assert runner._resolve_config_profile_name(tmp_path.parent / "config.json", {"published": {"path": "config.json"}}) is None

    samples = [
        BenchmarkSample(
            id="one",
            benchmark="synthetic",
            task_type="qa",
            question="q",
            ground_truth="a",
            history=[BenchmarkTurn(role="user", content="hi")],
            metadata={"history_shape": "full_input"},
        ),
        BenchmarkSample(
            id="two",
            benchmark="synthetic",
            task_type="qa",
            question="q",
            ground_truth="a",
            history=[],
            metadata={"history_shape": "focused_input"},
        ),
    ]
    shape = runner._summarize_sample_shapes(samples)
    assert shape["primary_shape"] == "mixed"
    assert shape["history_turns"] == {"min": 0, "max": 1, "avg": 0.5}
    assert runner._shape_tag("full_input") == "fulltext"
    assert runner._shape_tag("custom") == "custom"
    assert runner._split_chunk_by_words("superlongword", max_chars=5) == ["super", "longw", "ord"]
    assert len(runner._split_long_context_paragraph("first sentence. second sentence.", max_chars=16)) == 2
    assert runner._build_baseline_conversation(samples[0]) == [{"role": "user", "content": "hi"}]

    br = runner.BenchmarkRunner(baseline_profile="disabled", sample_retry_count=0)
    br._print_progress(
        "synthetic",
        1,
        2,
        {
            "id": "one",
            "mase": {
                "score": {"score": 1.0, "all_matched": True},
                "metrics": {"wall_clock_seconds": 0.1},
                "data_gap_audit": {"status": "ok"},
                "route_action": "search_memory",
            },
        },
        started_at=0.0,
        results=[{"mase": {"score": {"all_matched": True}}}],
    )
    assert "pass_rate=100.0%" in capsys.readouterr().out


def test_runner_run_sample_executes_fake_system_and_restores_environment(monkeypatch, tmp_path: Path) -> None:
    writes: list[dict[str, Any]] = []

    class FakeNotetaker:
        def write(self, **kwargs: Any) -> None:
            writes.append(kwargs)

    class FakeModelInterface:
        def __init__(self) -> None:
            self.reset = False

        def reset_call_log(self) -> None:
            self.reset = True

        def get_call_log(self) -> list[dict[str, Any]]:
            return [{"agent_type": "executor", "elapsed_seconds": 0.25, "usage": {"prompt_tokens": 4}}]

    class FakeRoute:
        action = "search_memory"
        keywords = ["relay"]

    class FakeSnapshot:
        def to_dict(self) -> dict[str, str]:
            return {"source": "fake"}

    class FakeTrace:
        answer = "Juniper-7"
        route = FakeRoute()
        planner = FakeSnapshot()
        thread = FakeSnapshot()
        executor_target = {"mode": "fake"}

    class FakeSystem:
        def __init__(self) -> None:
            self.notetaker_agent = FakeNotetaker()
            self.model_interface = FakeModelInterface()
            self.forced_routes: list[dict[str, Any] | None] = []

        def run_with_trace(self, question: str, *, log: bool, forced_route: dict[str, Any] | None = None) -> FakeTrace:
            assert question == "Which relay?"
            assert log is False
            self.forced_routes.append(forced_route)
            return FakeTrace()

    monkeypatch.setattr(runner, "MASESystem", FakeSystem)
    monkeypatch.setattr(
        runner,
        "baseline_ask_with_metrics",
        lambda conversation, question, profile, system_prompt, overrides: {
            "answer": "Juniper-7",
            "elapsed_seconds": 0.5,
            "usage": {"prompt_tokens": 1},
            "overrides": overrides,
        },
    )
    monkeypatch.setattr(runner, "score_sample", lambda sample, answer: {"score": 1.0, "all_matched": answer == "Juniper-7"})
    monkeypatch.setattr(
        runner,
        "audit_official_source_gap",
        lambda **kwargs: {"status": "ok", "case": str(kwargs["case_memory_dir"])},
    )
    monkeypatch.setenv("MASE_MEMORY_DIR", "previous-memory")
    monkeypatch.setenv("MASE_TASK_TYPE", "previous-task")

    sample = BenchmarkSample(
        id="case-1",
        benchmark="synthetic",
        task_type="long_memory",
        question="Which relay?",
        ground_truth="Juniper-7",
        history=[
            BenchmarkTurn(role="user", content="Remember Juniper-7.", timestamp="2024-01-01", session_id="s1"),
            BenchmarkTurn(role="assistant", content="Noted."),
        ],
        context="Context paragraph.",
        metadata={"dataset": "Synthetic", "question_type": "multi-session", "question_date": "2024-01-02"},
    )

    result = runner.BenchmarkRunner(
        baseline_profile="fake-baseline",
        baseline_timeout_seconds=3.0,
        sample_retry_count=0,
    ).run_sample(sample, tmp_path)

    assert result["mase"]["completed"] is True
    assert result["baseline"]["completed"] is True
    assert result["baseline"]["metrics"]["overrides"] == {"timeout_seconds": 3.0}
    assert result["mase"]["metrics"]["usage_totals"] == {"prompt_tokens": 4.0}
    assert result["retry_summary"]["used_retry"] is False
    assert any(row["metadata"]["source"] == "benchmark_history" for row in writes)
    assert any(row["metadata"]["source"] == "benchmark_context" for row in writes)
    assert os.environ["MASE_MEMORY_DIR"] == "previous-memory"
    assert os.environ["MASE_TASK_TYPE"] == "previous-task"
    assert "MASE_CURRENT_SAMPLE_HASH" not in os.environ


def test_runner_run_sample_retries_only_mase_infra_errors(tmp_path: Path) -> None:
    class RetryRunner(runner.BenchmarkRunner):
        def __init__(self) -> None:
            super().__init__(baseline_profile="disabled", sample_retry_count=2, sample_retry_delay_seconds=0)
            self.calls = 0

        def _run_sample_once(self, sample: BenchmarkSample, run_root: Path, attempt: int) -> dict[str, Any]:
            del sample, run_root
            self.calls += 1
            error_kind = "infra_error" if attempt == 1 else None
            return {
                "id": "case",
                "case_memory_dir": str(tmp_path / f"case-{attempt}"),
                "mase": {"error": "timeout" if error_kind else None, "error_kind": error_kind},
                "baseline": {"error": "baseline timeout", "error_kind": "infra_error"},
            }

    retry_runner = RetryRunner()
    result = retry_runner.run_sample(
        BenchmarkSample(id="case", benchmark="synthetic", task_type="qa", question="q", ground_truth="a"),
        tmp_path,
    )

    assert retry_runner.calls == 2
    assert result["attempt_count"] == 2
    assert result["retry_summary"]["used_retry"] is True
    assert result["retry_summary"]["attempts"][0]["mase_infra_error"] is True
    assert result["retry_summary"]["attempts"][1]["baseline_infra_error"] is True
