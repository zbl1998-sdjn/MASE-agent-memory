from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from benchmarks.runner import BenchmarkRunner


def _load_generalization_regression_module():
    script_dir = Path(__file__).resolve().parent / "scripts" / "benchmarks"
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
