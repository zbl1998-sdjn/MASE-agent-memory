from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase.benchmark_notetaker import BenchmarkNotetaker
from mase_tools.memory import api, db_core


@pytest.fixture()
def phase2_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = (tmp_path / "phase2.sqlite3").resolve()
    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    db_core._SCHEMA_READY.discard(str(db_path))
    return db_path


def test_history_hits_surface_for_update_questions(phase2_db: Path) -> None:
    del phase2_db
    api.mase2_upsert_fact("finance_budget", "budget", "800")
    api.mase2_upsert_fact("finance_budget", "budget", "1200", reason="user_correction")

    bn = BenchmarkNotetaker()
    results = bn.search(
        ["预算"],
        full_query="我之前把预算改成多少来着？",
        limit=5,
        scope_filters={"problem_type": "update", "include_history": True},
    )

    sources = [item.get("_source") for item in results]
    assert sources[0] == "entity_state"
    assert "entity_state_history" in sources
    history_hit = next(item for item in results if item.get("_source") == "entity_state_history")
    assert "800 -> 1200" in history_hit["content"]
    assert history_hit["conflict_status"] == "superseded"


def test_fact_sheet_includes_phase2_governance_metadata(phase2_db: Path) -> None:
    del phase2_db
    api.mase2_upsert_fact("service_config", "port", "8800")
    api.mase2_upsert_fact("service_config", "port", "9909", reason="manual_update")

    bn = BenchmarkNotetaker()
    results = bn.search(
        ["端口"],
        full_query="当前服务器端口是多少？",
        limit=3,
        scope_filters={"problem_type": "current_state"},
    )
    sheet = bn.build_fact_sheet(results)

    assert "state=updated" in sheet
    assert "freshness=" in sheet
    assert "history=1" in sheet
