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
from mase_tools.memory.db_core import (
    archive_entity_fact,
    consolidate_thread,
    gc_expired_session_context,
    get_entity_facts,
    get_session_context,
    list_episodic_snapshots,
    list_procedures,
    register_procedure,
    upsert_entity_fact,
    upsert_session_context,
)


@pytest.fixture()
def phase3_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = (tmp_path / "phase3.sqlite3").resolve()
    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    return db_path


def test_session_context_roundtrip_and_gc(phase3_db: Path) -> None:
    del phase3_db
    upsert_session_context("s1", "draft", "hello", ttl_days=1)
    upsert_session_context("s1", "expired", "old", ttl_days=0)

    live = get_session_context("s1")
    assert [row["context_key"] for row in live] == ["draft"]

    deleted = gc_expired_session_context()
    assert deleted >= 1


def test_register_and_list_procedures(phase3_db: Path) -> None:
    del phase3_db
    register_procedure("style-guide", "Always show provenance.", procedure_type="policy")
    rows = list_procedures(procedure_type="policy")
    assert rows
    assert rows[0]["procedure_key"] == "style-guide"


def test_consolidate_thread_creates_snapshot_and_marks_rows(phase3_db: Path) -> None:
    del phase3_db
    bn = BenchmarkNotetaker()
    bn.write("u1", "a1", summary="first", thread_id="thread-x")
    bn.write("u2", "a2", summary="second", thread_id="thread-x")

    result = consolidate_thread("thread-x")
    assert result["snapshot_id"] is not None
    assert result["source_count"] == 2

    snapshots = list_episodic_snapshots(thread_id="thread-x")
    assert snapshots
    rows = bn.fetch_all_chronological()
    thread_rows = [row for row in rows if row.get("thread_id") == "thread-x"]
    assert all(int(row.get("consolidated") or 0) == 1 for row in thread_rows)


def test_archived_fact_disappears_from_default_fact_view(phase3_db: Path) -> None:
    del phase3_db
    upsert_entity_fact("user_preferences", "city", "Hangzhou")
    assert get_entity_facts("user_preferences")
    archived = archive_entity_fact("user_preferences", "city")
    assert archived == 1
    assert get_entity_facts("user_preferences") == []


def test_scoped_session_context_and_procedure_can_coexist(phase3_db: Path) -> None:
    del phase3_db
    alpha_scope = {"tenant_id": "tenant-alpha", "workspace_id": "ws-red", "visibility": "shared"}
    beta_scope = {"tenant_id": "tenant-beta", "workspace_id": "ws-red", "visibility": "private"}

    upsert_session_context("session-1", "draft", "alpha-note", **alpha_scope)
    upsert_session_context("session-1", "draft", "beta-note", **beta_scope)
    alpha_rows = get_session_context("session-1", tenant_id="tenant-alpha", workspace_id="ws-red")
    beta_rows = get_session_context("session-1", tenant_id="tenant-beta", workspace_id="ws-red")
    assert [row["context_value"] for row in alpha_rows] == ["alpha-note"]
    assert [row["context_value"] for row in beta_rows] == ["beta-note"]

    register_procedure("style-guide", "Prefer provenance first.", procedure_type="policy", **alpha_scope)
    register_procedure("style-guide", "Prefer concise output.", procedure_type="policy", **beta_scope)
    alpha_procedures = list_procedures(procedure_type="policy", tenant_id="tenant-alpha", workspace_id="ws-red")
    beta_procedures = list_procedures(procedure_type="policy", tenant_id="tenant-beta", workspace_id="ws-red")
    assert alpha_procedures[0]["content"] == "Prefer provenance first."
    assert beta_procedures[0]["content"] == "Prefer concise output."
