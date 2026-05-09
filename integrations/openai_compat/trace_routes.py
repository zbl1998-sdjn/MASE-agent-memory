from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from integrations.openai_compat.responses import response_object
from integrations.openai_compat.runtime import ROOT
from mase.privacy import is_sensitive_key, redact_value
from mase.trace_recorder import get_trace_by_id, list_trace_summaries

router = APIRouter()


def trace_store_path() -> Path:
    path_value = str(os.environ.get("MASE_TRACE_RECORD_PATH") or "").strip()
    return Path(path_value).expanduser().resolve() if path_value else (ROOT / "memory" / "traces.jsonl").resolve()


def sanitize_trace_detail(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_trace_detail(item)
            for key, item in value.items()
            if not is_sensitive_key(str(key))
        }
    if isinstance(value, list):
        return [sanitize_trace_detail(item) for item in value]
    return redact_value(value, drop_sensitive_keys=True)


@router.get("/v1/ui/traces")
def ui_trace_summaries(
    trace_id: str | None = None,
    route_action: str | None = None,
    component: str | None = None,
    source_file: str | None = None,
    has_cloud_call: bool | None = None,
    min_cost: float | None = Query(default=None, ge=0.0),
    max_cost: float | None = Query(default=None, ge=0.0),
    has_risk: bool | None = None,
    limit: int | None = Query(default=None, ge=0, le=1000),
) -> dict[str, Any]:
    result = list_trace_summaries(
        trace_store_path(),
        trace_id=trace_id,
        route_action=route_action,
        component=component,
        source_file=source_file,
        has_cloud_call=has_cloud_call,
        min_cost=min_cost,
        max_cost=max_cost,
        has_risk=has_risk,
        limit=limit,
    )
    return response_object("mase.ui.traces", {"summaries": result["summaries"]}, result["metadata"])


@router.get("/v1/ui/traces/{trace_id}")
def ui_trace_detail(trace_id: str) -> dict[str, Any]:
    trace_path = trace_store_path()
    trace = get_trace_by_id(trace_path, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace_not_found")
    return response_object(
        "mase.ui.trace",
        {"trace": sanitize_trace_detail(trace)},
        {"path": str(trace_path), "trace_id": trace_id},
    )
