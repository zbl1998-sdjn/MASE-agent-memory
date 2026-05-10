from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PUBLISHABLE_LME_SCRIPTS = (
    "scripts/run_lme_full.py",
    "scripts/run_lme_full_cloud_swap.py",
    "scripts/run_lme_iter4_full500.py",
    "scripts/run_lme_iter5_full500.py",
)

RUNTIME_FILES = (
    "benchmarks/runner.py",
    "src/mase/mode_selector.py",
    "src/mase/engine.py",
    "src/mase/answer_normalization.py",
)

REQUIRED_EXTERNAL_ADAPTER_FILES = (
    "scripts/external_adapters/bamboo/run_mase_official.py",
    "scripts/external_adapters/bamboo/evaluate_official_compat.py",
    "scripts/external_adapters/nolima/run_mase_official.py",
    "scripts/external_adapters/nolima/run_mase_chunked.py",
)

EXTERNAL_RUNTIME_FILES = (
    *REQUIRED_EXTERNAL_ADAPTER_FILES,
    "benchmarks/external-benchmarks/BAMBOO/run_mase_official.py",
    "benchmarks/external-benchmarks/NoLiMa/run_mase_official.py",
    "benchmarks/external-benchmarks/NoLiMa/run_mase_chunked.py",
    "scripts/benchmarks/run_generalization_regression.py",
    "scripts/benchmarks/run_nolima_mase_smoke.py",
    "scripts/run_external_phase_a.py",
    "scripts/run_external_phase_a_reasoning.py",
    "scripts/run_external_phase_a_chunked.py",
)

FORBIDDEN_RUNTIME_SNIPPETS = (
    "MASE_CURRENT_QID",
    "qid.startswith",
    "qid.endswith",
    "question_id.startswith",
    "question_id.endswith",
    'os.environ["MASE_QID_BUCKET"] = "regular"',
    "os.environ['MASE_QID_BUCKET'] = 'regular'",
    'os.environ["MASE_QID_BUCKET"] = "gpt4_gen"',
    "os.environ['MASE_QID_BUCKET'] = 'gpt4_gen'",
    'os.environ["MASE_QID_BUCKET"] = "abstention"',
    "os.environ['MASE_QID_BUCKET'] = 'abstention'",
)

FORBIDDEN_EXTERNAL_RUNTIME_SNIPPETS = (
    "MASE_BENCHMARK_TEST_NAME",
    "MASE_BENCHMARK_PROFILE",
    'dataset_path.parent.parent / "outputs"',
    'needle_set_path.parent.parent / "outputs"',
    'PROJECT_ROOT / "results" / "nolima"',
    'ROOT / "results" / "external"',
    'case_memory_dir = run_dir / "case_memory" / sample_id',
    'suite_root / "raw" / f"{test',
)

DISABLED_QID_ROUTING_SNIPPETS = (
    "MASE_LME_ROUTE_BY_QID'] = '0'",
    'MASE_LME_ROUTE_BY_QID"] = "0"',
)


@dataclass(frozen=True)
class Finding:
    path: str
    message: str


def _read_repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def collect_findings() -> list[Finding]:
    findings: list[Finding] = []
    for path in REQUIRED_EXTERNAL_ADAPTER_FILES:
        if not (ROOT / path).exists():
            findings.append(Finding(path, "tracked external benchmark adapter is missing"))

    for path in RUNTIME_FILES:
        source = _read_repo_file(path)
        for snippet in FORBIDDEN_RUNTIME_SNIPPETS:
            if snippet in source:
                findings.append(Finding(path, f"forbidden id-routing snippet present: {snippet}"))

    for path in EXTERNAL_RUNTIME_FILES:
        full_path = ROOT / path
        if not full_path.exists():
            continue
        source = full_path.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_EXTERNAL_RUNTIME_SNIPPETS:
            if snippet in source:
                findings.append(Finding(path, f"forbidden external benchmark runtime snippet present: {snippet}"))

    for path in PUBLISHABLE_LME_SCRIPTS:
        source = _read_repo_file(path)
        if "MASE_LME_ROUTE_BY_QID" not in source:
            findings.append(Finding(path, "publishable LongMemEval script must set MASE_LME_ROUTE_BY_QID=0"))
            continue
        if not any(snippet in source for snippet in DISABLED_QID_ROUTING_SNIPPETS):
            findings.append(Finding(path, "publishable LongMemEval script does not force MASE_LME_ROUTE_BY_QID=0"))
        if "MASE_LME_ROUTE_BY_QID'] = '1'" in source or 'MASE_LME_ROUTE_BY_QID"] = "1"' in source:
            findings.append(Finding(path, "publishable LongMemEval script enables qid-bucket routing"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit benchmark anti-overfit guardrails.")
    parser.add_argument("--strict", action="store_true", help="exit non-zero when findings are present")
    args = parser.parse_args()

    findings = collect_findings()
    if not findings:
        print("Anti-overfit audit: no forbidden benchmark-id routing found.")
        return 0

    print("Anti-overfit audit: findings present.")
    for finding in findings:
        print(f"  - {finding.path}: {finding.message}")
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
