from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_runner_does_not_route_by_question_id_bucket() -> None:
    source = (ROOT / "benchmarks" / "runner.py").read_text(encoding="utf-8")

    assert "qid.endswith" not in source
    assert "qid.startswith" not in source
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
