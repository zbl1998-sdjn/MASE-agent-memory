from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_runner_does_not_route_by_question_id_bucket() -> None:
    source = (ROOT / "benchmarks" / "runner.py").read_text(encoding="utf-8")

    assert "qid.endswith" not in source
    assert "qid.startswith" not in source
    assert "MASE_CURRENT_QID" not in source
    assert '"abstention"' not in source
    assert '"gpt4_gen"' not in source
    assert '"regular"' not in source


def test_publishable_lme_scripts_disable_qid_bucket_routing() -> None:
    script_paths = [
        ROOT / "scripts" / "run_lme_full.py",
        ROOT / "scripts" / "run_lme_full_cloud_swap.py",
    ]

    for path in script_paths:
        source = path.read_text(encoding="utf-8")
        assert "MASE_LME_ROUTE_BY_QID" in source
        assert "MASE_LME_ROUTE_BY_QID'] = '0'" in source or 'MASE_LME_ROUTE_BY_QID"] = "0"' in source


def test_external_benchmark_entrypoints_do_not_route_or_store_by_raw_case_ids() -> None:
    adapter_paths = [
        ROOT / "scripts" / "external_adapters" / "bamboo" / "run_mase_official.py",
        ROOT / "scripts" / "external_adapters" / "bamboo" / "evaluate_official_compat.py",
        ROOT / "scripts" / "external_adapters" / "nolima" / "run_mase_official.py",
        ROOT / "scripts" / "external_adapters" / "nolima" / "run_mase_chunked.py",
    ]
    for path in adapter_paths:
        assert path.exists(), f"missing tracked external adapter: {path}"
        assert "MASE_BENCHMARK_PROFILE" not in path.read_text(encoding="utf-8")

    bamboo_path = ROOT / "benchmarks" / "external-benchmarks" / "BAMBOO" / "run_mase_official.py"
    tracked_bamboo_source = adapter_paths[0].read_text(encoding="utf-8")
    nolima_official_source = adapter_paths[2].read_text(encoding="utf-8")
    nolima_chunked_path = ROOT / "benchmarks" / "external-benchmarks" / "NoLiMa" / "run_mase_chunked.py"
    tracked_nolima_chunked_source = adapter_paths[3].read_text(encoding="utf-8")
    nolima_smoke_source = (ROOT / "scripts" / "benchmarks" / "run_nolima_mase_smoke.py").read_text(
        encoding="utf-8"
    )
    generalization_source = (
        ROOT / "scripts" / "benchmarks" / "run_generalization_regression.py"
    ).read_text(encoding="utf-8")

    assert 'PROJECT_ROOT / "results" / "nolima"' not in generalization_source
    assert 'suite_root / "raw" / f"{test' not in nolima_smoke_source
    assert "MASE_BENCHMARK_TEST_NAME" not in nolima_official_source
    assert "_case_artifact_id" in nolima_smoke_source
    assert 'dataset_path.parent.parent / "outputs"' not in tracked_bamboo_source
    assert 'case_memory_dir = run_dir / "case_memory" / sample_id' not in tracked_bamboo_source
    assert 'needle_set_path.parent.parent / "outputs"' not in tracked_nolima_chunked_source
    assert "_sample_artifact_id" in tracked_bamboo_source
    if bamboo_path.exists():
        bamboo_source = bamboo_path.read_text(encoding="utf-8")
        assert 'dataset_path.parent.parent / "outputs"' not in bamboo_source
        assert 'case_memory_dir = run_dir / "case_memory" / sample_id' not in bamboo_source
        assert "_sample_artifact_id" in bamboo_source
    if nolima_chunked_path.exists():
        nolima_chunked_source = nolima_chunked_path.read_text(encoding="utf-8")
        assert 'needle_set_path.parent.parent / "outputs"' not in nolima_chunked_source


def test_anti_overfit_audit_script_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/audit_anti_overfit.py", "--strict"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
