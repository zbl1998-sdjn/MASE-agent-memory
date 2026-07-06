"""时漂压力基准:生成器确定性 + 逐族端到端机械判分(tmp 库,固定时钟)。"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT, _ROOT / "benchmarks" / "staleness_pressure"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from generate_scenarios import build_scenarios, scenarios_manifest_sha256  # noqa: E402
from run_pressure import run_case  # noqa: E402

_NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)


def _case(case_id_prefix: str):
    matches = [s for s in build_scenarios(per_family=1) if s.case_id.startswith(case_id_prefix)]
    assert matches, f"no scenario with prefix {case_id_prefix}"
    return matches[0]


def test_generator_is_deterministic_and_ids_unique() -> None:
    first = build_scenarios(per_family=3)
    second = build_scenarios(per_family=3)
    assert scenarios_manifest_sha256(first) == scenarios_manifest_sha256(second)
    ids = [s.case_id for s in first]
    assert len(ids) == len(set(ids))
    families = {s.family for s in first}
    assert families == {"update", "conflict", "ttl", "unknown"}


def test_governed_update_adopts_latest_without_stale_leak(tmp_path: Path) -> None:
    dims = run_case(_case("update-governed-t30"), tmp_path, _NOW)
    assert dims == {"update_adopted": True, "stale_leak": False}


def test_degraded_update_leaks_stale_values(tmp_path: Path) -> None:
    dims = run_case(_case("update-degraded-t30"), tmp_path, _NOW)
    assert dims["stale_leak"] is True
    assert dims["update_adopted"] is False


def test_governed_conflict_reports_both_sides(tmp_path: Path) -> None:
    dims = run_case(_case("conflict-governed-t0"), tmp_path, _NOW)
    assert dims == {"conflict_reported": True, "stale_leak": False}


def test_degraded_conflict_goes_unreported(tmp_path: Path) -> None:
    dims = run_case(_case("conflict-degraded-t0"), tmp_path, _NOW)
    assert dims["conflict_reported"] is False


def test_ttl_boundary_fresh_verifies_and_expired_does_not(tmp_path: Path) -> None:
    fresh = run_case(_case("ttl-governed-t0"), tmp_path / "fresh", _NOW)
    expired = run_case(_case("ttl-governed-t30"), tmp_path / "expired", _NOW)
    assert fresh == {"ttl_correct": True, "stale_leak": False}
    assert expired == {"ttl_correct": True, "stale_leak": False}


def test_unknown_key_is_reported_honestly(tmp_path: Path) -> None:
    dims = run_case(_case("unknown-governed-t7"), tmp_path, _NOW)
    assert dims["unknown_honest"] is True
