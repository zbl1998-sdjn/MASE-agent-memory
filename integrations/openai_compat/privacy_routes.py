from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_query
from integrations.openai_compat.runtime import memory_service
from mase.auth_policy import AuthContext
from mase.privacy import privacy_report, redact_value, scan_value

router = APIRouter()


@router.post("/v1/ui/privacy/preview")
def ui_privacy_preview(
    payload: dict[str, Any],
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    findings = [finding.to_dict() for finding in scan_value(payload)]
    data = {
        "finding_count": len(findings),
        "findings": findings,
        "redacted": redact_value(payload),
    }
    return response_object("mase.ui.privacy_preview", data, {"generated_at": int(time.time())})


@router.get("/v1/ui/privacy/scan")
def ui_privacy_scan(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    facts = memory_service.list_facts(scope_filters=scope)[:limit]
    timeline = memory_service.recall_timeline(limit=limit, scope_filters=scope)
    sessions = memory_service.get_session_state("default", include_expired=True, scope_filters=scope)[:limit]
    procedures = memory_service.list_procedures(scope_filters=scope)[:limit]
    reports = [
        privacy_report(facts, source="facts"),
        privacy_report(timeline, source="timeline"),
        privacy_report(sessions, source="sessions"),
        privacy_report(procedures, source="procedures"),
    ]
    data = {
        "scope": scope,
        "reports": reports,
        "summary": {
            "item_count": sum(int(report["item_count"]) for report in reports),
            "finding_count": sum(int(report["finding_count"]) for report in reports),
            "sources_with_findings": [report["source"] for report in reports if int(report["finding_count"]) > 0],
        },
    }
    return response_object("mase.ui.privacy_scan", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_privacy_preview", "ui_privacy_scan"]
