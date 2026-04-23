from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_DIR = ROOT / "docs" / "benchmark_claims"


def _load(name: str) -> dict:
    return json.loads((CLAIMS_DIR / name).read_text(encoding="utf-8"))


def _read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_claim_manifests_exist_and_have_core_fields() -> None:
    for filename in ("longmemeval.json", "lveval.json", "nolima.json"):
        payload = _load(filename)
        assert "benchmark" in payload
        assert "claims" in payload
        assert isinstance(payload["claims"], dict)
        assert payload["claims"], f"{filename} must define at least one claim lane"


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
