from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "tests" / "data" / "failure_clusters"


def _load(name: str) -> dict:
    return json.loads((PACK_DIR / name).read_text(encoding="utf-8"))


def test_failure_cluster_pack_has_required_benchmarks() -> None:
    manifest = _load("manifest.json")
    assert manifest["benchmarks"] == ["longmemeval", "lveval", "nolima"]

    for filename in ("longmemeval.json", "lveval.json", "nolima.json"):
        payload = _load(filename)
        assert payload["cases"], f"{filename} must declare at least one case"
        for case in payload["cases"]:
            assert "id" in case
            assert "failure_mode" in case
            assert "guardrail" in case
