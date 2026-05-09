from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_query
from integrations.openai_compat.runtime import memory_service
from mase.auth_policy import AuthContext
from mase.drift_detector import detect_memory_drift

router = APIRouter()


@router.get("/v1/ui/drift")
def ui_drift_report(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    category: str | None = None,
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    facts = memory_service.list_facts(category=category, scope_filters=scope)
    data = detect_memory_drift(facts)
    data["scope"] = scope
    data["category"] = category
    return response_object("mase.ui.drift", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_drift_report"]
