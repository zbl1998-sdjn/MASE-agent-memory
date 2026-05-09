from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_query
from integrations.openai_compat.runtime import ROOT, memory_service
from mase.auth_policy import AuthContext
from mase.quality_score import build_quality_report
from mase.trace_recorder import list_trace_summaries

router = APIRouter()


def _trace_store_path() -> Path:
    return (ROOT / "memory" / "traces.jsonl").resolve()


@router.get("/v1/ui/quality")
def ui_quality_report(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    facts = memory_service.list_facts(scope_filters=scope)[:limit]
    recall_hits = (
        memory_service.search_memory([part for part in query.split() if part] or [query], full_query=query, limit=10, include_history=True, scope_filters=scope)
        if query
        else []
    )
    traces = list_trace_summaries(_trace_store_path(), limit=25).get("summaries", [])
    data = build_quality_report(facts=facts, recall_hits=recall_hits, trace_summaries=traces)
    data["scope"] = scope
    data["query"] = query
    return response_object("mase.ui.quality", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_quality_report"]
