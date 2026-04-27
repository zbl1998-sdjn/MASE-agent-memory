from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from integrations.openai_compat.server import (
    MemoryRecallRequest,
    MemoryTimelineRequest,
    memory_current_state,
    memory_explain,
    memory_recall,
    memory_timeline,
)
from mase import MemoryService


@pytest.fixture()
def openai_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = (tmp_path / "openai-memory.sqlite3").resolve()
    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    return db_path


def test_openai_memory_endpoints_return_hits(openai_db: Path) -> None:
    del openai_db
    service = MemoryService()
    service.remember_event("oa-thread", "user", "Project codename is Aurora")
    service.upsert_fact("project_status", "codename", "Aurora")

    recall = memory_recall(MemoryRecallRequest(query="Project codename", top_k=3, include_history=True))
    current = memory_current_state(MemoryRecallRequest(query="codename", top_k=3))
    explain = memory_explain(MemoryRecallRequest(query="What is the codename?", top_k=3))
    timeline = memory_timeline(MemoryTimelineRequest(thread_id="oa-thread", limit=10))

    assert recall["data"]
    assert current["data"]
    assert explain["data"]["hits"]
    assert timeline["data"]


def test_openai_memory_endpoints_return_scope_metadata(openai_db: Path) -> None:
    del openai_db
    service = MemoryService()
    scope = {"tenant_id": "tenant-oa", "workspace_id": "ws-api", "visibility": "shared"}
    service.remember_event("oa-thread-scoped", "user", "Scoped codename is Nebula", scope_filters=scope)
    service.upsert_fact("project_status", "codename", "Nebula", scope_filters=scope)

    recall = memory_recall(MemoryRecallRequest(query="codename", top_k=3, include_history=True, **scope))
    explain = memory_explain(MemoryRecallRequest(query="What is the codename?", top_k=3, **scope))
    timeline = memory_timeline(MemoryTimelineRequest(thread_id="oa-thread-scoped", limit=10, **scope))

    assert recall["metadata"]["scope"] == scope
    assert recall["metadata"]["result_count"] >= 1
    assert explain["data"]["scope"] == scope
    assert explain["data"]["metadata"]["hit_count"] >= 1
    assert timeline["metadata"]["scope"] == scope
    assert timeline["data"]
