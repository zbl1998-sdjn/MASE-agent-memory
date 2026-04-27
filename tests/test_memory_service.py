from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase import MemoryService


@pytest.fixture()
def service_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = (tmp_path / "memory-service.sqlite3").resolve()
    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    return db_path


def test_memory_service_end_to_end(service_db: Path) -> None:
    del service_db
    service = MemoryService()
    service.remember_event("svc-thread", "user", "My budget is 800")
    correction = service.correct_memory("svc-thread", "Actually my budget is 1200", extra_keywords=["budget"])
    service.upsert_fact("finance_budget", "budget", "1200", source_log_id=correction["new_log_id"])

    hits = service.search_memory(["budget"], full_query="what is my budget now?", include_history=True)
    assert hits
    assert hits[0]["_source"] == "entity_state"


def test_memory_service_consolidate_and_procedure(service_db: Path) -> None:
    del service_db
    service = MemoryService()
    service.remember_event("svc-thread", "user", "Need a release checklist")
    service.remember_event("svc-thread", "assistant", "Recorded the checklist")
    snapshot = service.consolidate_session("svc-thread")
    service.register_procedure("release-checklist", "Run tests before ship.", procedure_type="workflow")

    assert snapshot["snapshot_id"] is not None
    procedures = service.list_procedures("workflow")
    assert procedures


def test_memory_service_scope_filters_isolate_facts_logs_and_metadata(service_db: Path) -> None:
    del service_db
    service = MemoryService()
    alpha_scope = {"tenant_id": "tenant-alpha", "workspace_id": "ws-core", "visibility": "shared"}
    beta_scope = {"tenant_id": "tenant-beta", "workspace_id": "ws-core", "visibility": "private"}

    service.remember_event("scope-thread", "user", "Alpha budget is 1000", scope_filters=alpha_scope)
    service.remember_event("scope-thread", "user", "Beta budget is 2000", scope_filters=beta_scope)
    service.upsert_fact("finance_budget", "budget", "1000", scope_filters=alpha_scope)
    service.upsert_fact("finance_budget", "budget", "2000", scope_filters=beta_scope)

    alpha_hits = service.search_memory(
        ["budget"],
        full_query="what is the budget?",
        include_history=True,
        scope_filters=alpha_scope,
    )
    beta_hits = service.search_memory(
        ["budget"],
        full_query="what is the budget?",
        include_history=True,
        scope_filters=beta_scope,
    )

    assert alpha_hits[0]["entity_value"] == "1000"
    assert beta_hits[0]["entity_value"] == "2000"
    assert all(hit.get("tenant_id") == "tenant-alpha" for hit in alpha_hits)
    assert all(hit.get("tenant_id") == "tenant-beta" for hit in beta_hits)

    alpha_timeline = service.recall_timeline(thread_id="scope-thread", scope_filters=alpha_scope)
    beta_timeline = service.recall_timeline(thread_id="scope-thread", scope_filters=beta_scope)
    assert [row["content"] for row in alpha_timeline] == ["Alpha budget is 1000"]
    assert [row["content"] for row in beta_timeline] == ["Beta budget is 2000"]

    explain = service.explain_memory_answer("budget", scope_filters=alpha_scope)
    assert explain["scope"] == alpha_scope
    assert explain["metadata"]["source_counts"]["entity_state"] >= 1
