from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from integrations.openai_compat.auth_dependencies import get_auth_context, is_read_only_mode, require_permission
from integrations.openai_compat.responses import response_object
from mase.audit_log import list_audit_events
from mase.auth_policy import ROLE_PERMISSIONS, AuthContext

router = APIRouter()


@router.get("/v1/ui/auth/policy")
def ui_auth_policy(request: Request) -> dict[str, Any]:
    context = get_auth_context(request)
    data = {
        "actor": asdict(context),
        "roles": [{"role": role, "permissions": list(permissions)} for role, permissions in ROLE_PERMISSIONS.items()],
        "read_only": is_read_only_mode(),
    }
    return response_object("mase.ui.auth.policy", data, {"generated_at": int(time.time())})


@router.get("/v1/ui/audit/events")
def ui_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    _: AuthContext = Depends(require_permission("audit")),
) -> dict[str, Any]:
    result = list_audit_events(limit=limit, actor_id=actor_id, action=action, resource_type=resource_type)
    metadata = dict(result["metadata"])
    metadata["generated_at"] = int(time.time())
    return response_object("mase.ui.audit.events", {"events": result["events"]}, metadata)
