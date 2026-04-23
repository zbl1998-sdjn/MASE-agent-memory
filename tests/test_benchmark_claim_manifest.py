from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_DIR = ROOT / "docs" / "benchmark_claims"

VALID_EVIDENCE_STATUSES = {"tracked", "local_generated_untracked"}
REQUIRED_CLAIM_FIELDS = {"score_pct", "pass_count", "sample_count", "metric", "config_profile", "evidence"}
REQUIRED_EVIDENCE_FIELDS = {"path", "status"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _discover_manifests() -> list[Path]:
    manifests = sorted(CLAIMS_DIR.glob("*.json"))
    assert manifests, f"No JSON manifests found under {CLAIMS_DIR}"
    return manifests


def test_claim_manifests_exist_and_have_core_fields() -> None:
    for manifest_path in _discover_manifests():
        payload = _load(manifest_path)
        name = manifest_path.name
        assert "benchmark" in payload, f"{name}: missing 'benchmark'"
        assert "claims" in payload, f"{name}: missing 'claims'"
        assert isinstance(payload["claims"], dict), f"{name}: 'claims' must be a dict"
        assert payload["claims"], f"{name} must define at least one claim lane"


def test_claim_manifests_per_claim_required_fields() -> None:
    for manifest_path in _discover_manifests():
        payload = _load(manifest_path)
        name = manifest_path.name
        for lane, claim in payload["claims"].items():
            for field in REQUIRED_CLAIM_FIELDS:
                assert field in claim, (
                    f"{name} / lane '{lane}': missing required field '{field}'"
                )


def test_claim_manifests_evidence_items_have_required_fields() -> None:
    for manifest_path in _discover_manifests():
        payload = _load(manifest_path)
        name = manifest_path.name
        for lane, claim in payload["claims"].items():
            assert isinstance(claim.get("evidence"), list), (
                f"{name} / lane '{lane}': 'evidence' must be a list"
            )
            for idx, item in enumerate(claim["evidence"]):
                for field in REQUIRED_EVIDENCE_FIELDS:
                    assert field in item, (
                        f"{name} / lane '{lane}' / evidence[{idx}]: missing '{field}'"
                    )


def test_claim_manifests_evidence_status_values() -> None:
    for manifest_path in _discover_manifests():
        payload = _load(manifest_path)
        name = manifest_path.name
        for lane, claim in payload["claims"].items():
            for idx, item in enumerate(claim.get("evidence", [])):
                status = item.get("status")
                assert status in VALID_EVIDENCE_STATUSES, (
                    f"{name} / lane '{lane}' / evidence[{idx}]: "
                    f"'status' must be one of {sorted(VALID_EVIDENCE_STATUSES)!r}, got {status!r}"
                )


def test_public_docs_reference_tracked_claim_language() -> None:
    readme = _read_text("README.md")
    readme_en = _read_text("docs/README_en.md")
    benchmarks = _read_text("BENCHMARKS.md")
    publish = _read_text("docs/PUBLISH_CHECKLIST.md")

    assert "docs/benchmark_claims/" in benchmarks
    assert "official substring" in readme
    assert "official substring" in readme_en
    assert "tracked claim manifest" in publish


def test_longmemeval_claim_lane_is_spelled_out() -> None:
    readme = _read_text("README.md")
    benchmarks = _read_text("BENCHMARKS.md")

    assert "84.8% (424/500)" in readme
    assert "61.0% (305/500)" in readme
    assert "LLM-judge, full_500 combined lane" in benchmarks
    assert "official substring-comparable lane" in benchmarks
