from __future__ import annotations

from pathlib import Path

from scripts.audit_repo_hygiene import find_local_artifacts, main, render_report


def test_repo_hygiene_clean_root_passes(tmp_path: Path) -> None:
    assert find_local_artifacts(tmp_path) == []
    assert main(["--root", str(tmp_path), "--strict"]) == 0


def test_repo_hygiene_detects_local_only_dirs_and_files(tmp_path: Path) -> None:
    (tmp_path / "memory_runs").mkdir()
    (tmp_path / "benchmarks" / "external-benchmarks" / "BAMBOO" / "outputs").mkdir(parents=True)
    (tmp_path / "benchmarks" / "external-benchmarks" / "BAMBOO.zip").write_text("zip", encoding="utf-8")
    (tmp_path / "config.lme_cloud_swap.json").write_text("{}", encoding="utf-8")
    (tmp_path / "_local.log").write_text("runtime output", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "_local.log").write_text("runtime output", encoding="utf-8")

    assert find_local_artifacts(tmp_path) == [
        "_local.log",
        "benchmarks/external-benchmarks/BAMBOO.zip",
        "benchmarks/external-benchmarks/BAMBOO/outputs",
        "config.lme_cloud_swap.json",
        "memory_runs",
        "scripts/_local.log",
    ]


def test_repo_hygiene_default_is_advisory(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()

    assert main(["--root", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "--strict"]) == 1


def test_repo_hygiene_report_mentions_external_run_directory(tmp_path: Path) -> None:
    report = render_report(["memory_runs"], tmp_path)

    assert "E:/MASE-runs" in report
    assert "MASE_RUNS_DIR" in report
    assert "--sizes" in report
