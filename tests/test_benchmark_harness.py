from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from benchmarks.runner import BenchmarkRunner
from benchmarks.schemas import BenchmarkSample


def _load_generalization_regression_module():
    script_dir = Path(__file__).resolve().parent.parent / "scripts" / "benchmarks"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    spec = importlib.util.spec_from_file_location(
        "run_generalization_regression",
        script_dir / "run_generalization_regression.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    runner = BenchmarkRunner()
    benchmark_names = [
        "generalization_smoke",
        "longmemeval_smoke",
        "lveval_smoke",
        "mmlu_smoke",
        "gsm8k_smoke",
        "humaneval_smoke",
    ]
    summaries = [runner.run_benchmark(name, sample_limit=1) for name in benchmark_names]
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


def test_official_max_only_keeps_longmemeval_and_max_suites() -> None:
    module = _load_generalization_regression_module()
    suites = [
        {"name": "longmemeval-official-smoke", "kind": "longmemeval"},
        {"name": "bamboo-official-smoke", "kind": "bamboo"},
        {"name": "bamboo-official-max", "kind": "bamboo"},
        {"name": "nolima-official-smoke", "kind": "nolima"},
        {"name": "nolima-official-max", "kind": "nolima"},
    ]

    selected = module._select_active_suites(suites, set(), official_max_only=True)
    selected_names = [suite["name"] for suite in selected]

    assert "longmemeval-official-smoke" in selected_names
    assert "bamboo-official-max" in selected_names
    assert "nolima-official-max" in selected_names
    assert "bamboo-official-smoke" not in selected_names
    assert "nolima-official-smoke" not in selected_names


def test_generalization_comparison_prefers_max_suites(monkeypatch) -> None:
    module = _load_generalization_regression_module()
    monkeypatch.setattr(
        module,
        "_load_previous_reference",
        lambda: {
            "bamboo_max": [
                {"task": "meetingqa", "score": "accuracy: 80.0"},
                {"task": "showssort", "score": "Cornordinary_index: 70.0"},
            ],
            "bamboo_smoke": [
                {"task": "meetingqa", "score": "accuracy: 10.0"},
                {"task": "showssort", "score": "Cornordinary_index: 20.0"},
            ],
            "nolima_previous_summary": {"smoke_accuracy": 0.5, "extended_accuracy": 0.6},
            "nolima_max_summary": {"smoke_accuracy": 0.8, "extended_accuracy": 0.9},
        },
    )

    comparison = module._build_comparison(
        {
            "suites": [
                {
                    "name": "bamboo-official-smoke",
                    "metrics": {
                        "meetingqa": {"metric_value": "20.0"},
                        "showssort": {"metric_value": "40.0"},
                    },
                },
                {
                    "name": "bamboo-official-max",
                    "metrics": {
                        "meetingqa": {"metric_value": "60.0"},
                        "showssort": {"metric_value": "55.0"},
                    },
                },
                {
                    "name": "nolima-official-smoke",
                    "metrics": {"smoke_accuracy": 0.1, "extended_accuracy": 0.2},
                },
                {
                    "name": "nolima-official-max",
                    "metrics": {"smoke_accuracy": 0.9, "extended_accuracy": 1.0},
                },
            ]
        }
    )

    assert comparison["selected_suites"]["bamboo"] == "bamboo-official-max"
    assert comparison["selected_suites"]["nolima"] == "nolima-official-max"
    assert comparison["delta_vs_previous_smoke"]["bamboo"]["meetingqa"]["delta"] == -20.0
    assert comparison["delta_vs_previous_smoke"]["bamboo"]["showssort"]["delta"] == -15.0
    assert comparison["delta_vs_previous_smoke"]["nolima"]["smoke_accuracy_delta"] == 0.1
    assert comparison["delta_vs_previous_smoke"]["nolima"]["extended_accuracy_delta"] == 0.1


def test_nolima_official_max_metrics_are_loaded(tmp_path, monkeypatch) -> None:
    module = _load_generalization_regression_module()
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)

    run_dir = tmp_path / "external-benchmarks" / "NoLiMa" / "outputs" / "official-max-needle_set_2000_depth50"
    run_dir.mkdir(parents=True)
    summary_payload = {
        "test_count": 58,
        "haystack_count": 5,
        "summary": {
            "processed": 290,
            "passed": 80,
            "failed": 210,
            "accuracy": 0.2759,
        },
    }
    (run_dir / "nolima.summary.json").write_text(json.dumps(summary_payload), encoding="utf-8")

    metrics = module._parse_suite_metrics(
        "nolima-official-max",
        [
            {
                "command": (
                    "python .\\external-benchmarks\\NoLiMa\\run_mase_official.py "
                    "--run-dir external-benchmarks\\NoLiMa\\outputs\\official-max-needle_set_2000_depth50"
                )
            }
        ],
    )

    assert metrics["summary_path"].endswith("nolima.summary.json")
    assert metrics["sample_count"] == 290
    assert metrics["processed"] == 290
    assert metrics["passed"] == 80
    assert metrics["failed"] == 210
    assert metrics["accuracy"] == 0.2759


def test_nolima_smoke_metrics_are_loaded_from_runs_dir(tmp_path, monkeypatch) -> None:
    module = _load_generalization_regression_module()
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(module, "RUNS_DIR", runs_dir)

    summary_path = runs_dir / "results" / "nolima" / "mase-nolima-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "smoke": {"accuracy": 0.5, "sample_count": 8, "adapter_error_count": 0},
                "extended": {"accuracy": 0.25, "sample_count": 8, "adapter_error_count": 1},
            }
        ),
        encoding="utf-8",
    )

    metrics = module._parse_suite_metrics("nolima-official-smoke", [])

    assert metrics["summary_path"] == str(summary_path)
    assert metrics["smoke_accuracy"] == 0.5
    assert metrics["extended_accuracy"] == 0.25


def test_generalization_manifest_uses_runs_dir_for_external_outputs() -> None:
    module = _load_generalization_regression_module()
    manifest = module._load_manifest(module.DEFAULT_MANIFEST)

    for suite in manifest["suites"]:
        for command in suite.get("commands") or []:
            if "outputs" not in command:
                continue
            assert "{runs_dir}" in command


def test_generalization_command_expands_runs_dir(monkeypatch, tmp_path) -> None:
    module = _load_generalization_regression_module()
    monkeypatch.setattr(module, "RUNS_DIR", tmp_path / "runs")

    expanded = module._expand_command("tool --run-dir {runs_dir}\\external-benchmarks\\BAMBOO\\outputs\\smoke")

    assert str(tmp_path / "runs") in expanded
    assert "{runs_dir}" not in expanded


def test_run_benchmark_config_profile_captured_before_samples_run(monkeypatch, tmp_path) -> None:
    """Issue B: config_profile must be resolved at run start, not re-resolved after
    samples have run (which may mutate MASE_CONFIG_PATH via MASESystem.__init__)."""
    from benchmarks import runner as runner_module

    profiles = {"my-profile": {"path": "config.json", "intent": "published"}}
    monkeypatch.setattr(runner_module, "_load_config_profiles", lambda: profiles)
    monkeypatch.setattr(runner_module, "_load_benchmark_fallbacks", lambda: {})
    monkeypatch.setattr(runner_module, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner_module, "MEMORY_RUNS_DIR", tmp_path)

    # Tracks whether load_benchmark_samples has run (simulates env mutation during sampling)
    state = {"samples_loaded": False}

    def fake_load_samples(*args, **kwargs):
        state["samples_loaded"] = True
        return []

    def controlled_resolve():
        # Before samples run: env points to a repo-root config that matches the profile
        # After samples run: env has been mutated to a different path (simulates MASESystem.__init__)
        if state["samples_loaded"]:
            return (runner_module.BASE_DIR / "config.other.json").resolve()
        return (runner_module.BASE_DIR / "config.json").resolve()

    monkeypatch.setattr(runner_module, "load_benchmark_samples", fake_load_samples)
    br = runner_module.BenchmarkRunner(baseline_profile="disabled")
    monkeypatch.setattr(runner_module, "resolve_config_path", controlled_resolve)

    summary = br.run_benchmark("any_benchmark")

    # With bug: resolve_config_path() called AFTER load_benchmark_samples (state["samples_loaded"]=True)
    #   → returns config.other.json → no match → summary["config_profile"] = None
    # With fix: resolve_config_path() captured BEFORE load_benchmark_samples
    #   → returns config.json → matches "my-profile"
    assert summary["config_profile"] == "my-profile"
    assert summary["run_protocol"]["id_routing_allowed"] is False
    assert summary["run_protocol"]["sample_id_usage"] == "result_reporting_only"
    assert summary["run_protocol"]["runtime_sample_identifier"] == "sha256_hash"
    assert summary["dataset_provenance"]["sample_count"] == 0


def test_dataset_provenance_hashes_samples_without_raw_answers() -> None:
    from benchmarks import runner as runner_module

    samples = [
        BenchmarkSample(
            id="synthetic-case-001",
            benchmark="synthetic",
            task_type="qa",
            question="Which relay station did the operator choose?",
            ground_truth="relay-seven-secret",
            metadata={"dataset": "synthetic_holdout", "length": "short"},
        )
    ]

    provenance = runner_module._build_dataset_provenance(
        "synthetic",
        samples,
        path=None,
        config="holdout",
        split="test",
    )

    serialized = json.dumps(provenance, ensure_ascii=False, sort_keys=True)
    assert provenance["sample_count"] == 1
    assert provenance["source"] == "hf-default"
    assert provenance["sample_ids_sha256"]
    assert provenance["sample_payload_sha256"]
    assert "relay-seven-secret" not in serialized


def test_dataset_provenance_changes_when_sample_content_changes() -> None:
    from benchmarks import runner as runner_module

    first = [
        BenchmarkSample(
            id="same-id",
            benchmark="synthetic",
            task_type="qa",
            question="What is the port?",
            ground_truth="9912",
        )
    ]
    second = [
        BenchmarkSample(
            id="same-id",
            benchmark="synthetic",
            task_type="qa",
            question="What is the port?",
            ground_truth="9913",
        )
    ]

    first_provenance = runner_module._build_dataset_provenance("synthetic", first, path=None, config=None, split=None)
    second_provenance = runner_module._build_dataset_provenance("synthetic", second, path=None, config=None, split=None)

    assert first_provenance["sample_ids_sha256"] == second_provenance["sample_ids_sha256"]
    assert first_provenance["sample_payload_sha256"] != second_provenance["sample_payload_sha256"]


def test_benchmark_history_ingest_exposes_only_hashed_sample_id() -> None:
    from benchmarks import runner as runner_module
    from benchmarks.schemas import BenchmarkTurn

    class FakeNotetaker:
        def __init__(self) -> None:
            self.rows = []

        def write(self, **kwargs):
            self.rows.append(kwargs)

    class FakeSystem:
        def __init__(self) -> None:
            self.notetaker_agent = FakeNotetaker()

    system = FakeSystem()
    raw_id = "gpt4_sensitive_bucket_001_abs"

    runner_module._ingest_turns_into_mase(
        system,  # type: ignore[arg-type]
        [BenchmarkTurn(role="user", content="Remember that the relay is Juniper-7.")],
        benchmark_question_id=raw_id,
    )

    metadata = system.notetaker_agent.rows[0]["metadata"]
    assert metadata["benchmark_id_visibility"] == "hashed"
    assert metadata["benchmark_sample_hash"] == runner_module._hash_text(raw_id)
    assert "benchmark_question_id" not in metadata
    assert raw_id not in json.dumps(metadata, ensure_ascii=False)


def test_sample_artifact_id_is_hash_not_raw_id() -> None:
    from benchmarks import runner as runner_module

    sample = BenchmarkSample(
        id="gpt4_sensitive_bucket_001_abs",
        benchmark="synthetic",
        task_type="qa",
        question="What is active?",
        ground_truth="Juniper-7",
    )

    artifact_id = runner_module._sample_artifact_id(sample)

    assert artifact_id.startswith("sample-")
    assert "gpt4" not in artifact_id
    assert "abs" not in artifact_id


def test_benchmark_runner_uses_mase_runs_dir(monkeypatch, tmp_path) -> None:
    import importlib
    from benchmarks import runner as runner_module

    monkeypatch.setenv("MASE_RUNS_DIR", str(tmp_path / "runs"))
    reloaded = importlib.reload(runner_module)

    assert reloaded.RESULTS_DIR == (tmp_path / "runs" / "results").resolve()
    assert reloaded.MEMORY_RUNS_DIR == (tmp_path / "runs" / "memory_runs").resolve()

    monkeypatch.delenv("MASE_RUNS_DIR", raising=False)
    importlib.reload(runner_module)


def test_runner_prefers_mase_module_imports() -> None:
    source = (Path(__file__).resolve().parents[1] / "benchmarks" / "runner.py").read_text(encoding="utf-8")
    assert "from mase.model_interface import" in source
    assert "from mase.topic_threads import" in source


def test_longmemeval_batch_uses_mase_model_interface() -> None:
    """run_api_hotswap_longmemeval_batch.py must import and use resolve_config_path
    from mase.model_interface directly (not transitively via the smoke script)."""
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "benchmarks"
        / "run_api_hotswap_longmemeval_batch.py"
    ).read_text(encoding="utf-8")
    assert "from mase.model_interface import" in source
    assert "resolve_config_path" in source


def test_generalization_smoke_suite_is_independent_of_public_benchmark_ids() -> None:
    from benchmarks.registry import load_benchmark_samples

    samples = load_benchmark_samples("generalization_smoke")

    assert len(samples) >= 3
    assert {sample.task_type for sample in samples} >= {"long_memory", "long_context_qa", "math"}
    for sample in samples:
        normalized_id = sample.id.lower()
        assert "longmemeval" not in normalized_id
        assert "lveval" not in normalized_id
        assert "nolima" not in normalized_id
        assert "bamboo" not in normalized_id
