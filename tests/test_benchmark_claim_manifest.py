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


def _metric_payload(evidence: dict, metric: str) -> dict:
    candidates = [metric]
    if metric == "substring":
        candidates.append("official_substring")
    if metric.endswith("_diagnostic"):
        candidates.append(metric.removesuffix("_diagnostic"))

    for key in candidates:
        value = evidence.get(key)
        if isinstance(value, dict):
            return value
    raise AssertionError(f"Evidence missing metric payload for {metric!r}; tried {candidates!r}")


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


def test_publishable_claim_lanes_use_tracked_evidence() -> None:
    for manifest_path in _discover_manifests():
        payload = _load(manifest_path)
        name = manifest_path.name
        for lane, claim in payload["claims"].items():
            if claim.get("publishable_headline") is False:
                continue
            for idx, item in enumerate(claim.get("evidence", [])):
                assert item.get("status") == "tracked", (
                    f"{name} / lane '{lane}' / evidence[{idx}]: "
                    "publishable lanes must use tracked evidence"
                )


def test_tracked_evidence_files_exist_and_match_claim_scores() -> None:
    for manifest_path in _discover_manifests():
        payload = _load(manifest_path)
        name = manifest_path.name
        for lane, claim in payload["claims"].items():
            for idx, item in enumerate(claim.get("evidence", [])):
                if item.get("status") != "tracked":
                    continue
                evidence_path = ROOT / str(item.get("path") or "")
                assert evidence_path.exists(), (
                    f"{name} / lane '{lane}' / evidence[{idx}]: missing tracked evidence file {evidence_path}"
                )
                assert evidence_path.suffix == ".json", (
                    f"{name} / lane '{lane}' / evidence[{idx}]: tracked evidence must be machine-readable JSON"
                )
                evidence = _load(evidence_path)
                metric = _metric_payload(evidence, str(claim["metric"]))
                assert evidence.get("sample_count") == claim["sample_count"], (
                    f"{name} / lane '{lane}': evidence sample_count does not match claim"
                )
                assert metric.get("pass_count") == claim["pass_count"], (
                    f"{name} / lane '{lane}': evidence pass_count does not match claim"
                )
                assert metric.get("score_pct") == claim["score_pct"], (
                    f"{name} / lane '{lane}': evidence score_pct does not match claim"
                )


def test_publishable_tracked_evidence_declares_anti_overfit_protocol() -> None:
    valid_capture_statuses = {"captured_by_runner", "summary_only_legacy"}
    for manifest_path in _discover_manifests():
        payload = _load(manifest_path)
        name = manifest_path.name
        for lane, claim in payload["claims"].items():
            if claim.get("publishable_headline") is False:
                continue
            for idx, item in enumerate(claim.get("evidence", [])):
                if item.get("status") != "tracked":
                    continue
                evidence_path = ROOT / str(item.get("path") or "")
                evidence = _load(evidence_path)

                provenance = evidence.get("dataset_provenance")
                assert isinstance(provenance, dict), (
                    f"{name} / lane '{lane}' / evidence[{idx}]: missing dataset_provenance"
                )
                assert provenance.get("capture_status") in valid_capture_statuses, (
                    f"{name} / lane '{lane}' / evidence[{idx}]: invalid provenance capture_status"
                )
                assert provenance.get("sample_count") == claim["sample_count"], (
                    f"{name} / lane '{lane}' / evidence[{idx}]: provenance sample_count mismatch"
                )
                assert str(provenance.get("source") or "").strip(), (
                    f"{name} / lane '{lane}' / evidence[{idx}]: provenance source is required"
                )

                protocol = evidence.get("run_protocol")
                assert isinstance(protocol, dict), (
                    f"{name} / lane '{lane}' / evidence[{idx}]: missing run_protocol"
                )
                assert protocol.get("id_routing_allowed") is False, (
                    f"{name} / lane '{lane}' / evidence[{idx}]: id routing must be disabled"
                )
                assert protocol.get("sample_id_usage") == "result_reporting_only", (
                    f"{name} / lane '{lane}' / evidence[{idx}]: raw sample ids must stay in result reporting only"
                )
                assert protocol.get("runtime_sample_identifier") == "sha256_hash", (
                    f"{name} / lane '{lane}' / evidence[{idx}]: runtime sample identifier must be hashed"
                )

                anti_overfit = evidence.get("anti_overfit")
                assert isinstance(anti_overfit, dict), (
                    f"{name} / lane '{lane}' / evidence[{idx}]: missing anti_overfit"
                )
                assert anti_overfit.get("qid_bucket_routing") == "disabled", (
                    f"{name} / lane '{lane}' / evidence[{idx}]: qid-bucket routing must be disabled"
                )
                assert anti_overfit.get("uses_failed_slice_retry") is False, (
                    f"{name} / lane '{lane}' / evidence[{idx}]: publishable lanes cannot use failed-slice retry"
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

    assert "61.0% (305/500)" in readme
    assert "80.2% (401/500)" in readme
    assert "post-hoc combined/retry diagnostic" in readme
    assert "LLM-judge lane on the same iter2 full_500 run" in benchmarks
    assert "official substring-comparable lane" in benchmarks
