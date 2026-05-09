from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_request
from integrations.openai_compat.runtime import memory_service
from integrations.openai_compat.schemas import WhyNotRememberedRequest
from mase.auth_policy import AuthContext
from mase.why_not_remembered import diagnose_why_not_remembered

router = APIRouter()


@router.post("/v1/ui/why-not-remembered")
def ui_why_not_remembered(
    req: WhyNotRememberedRequest,
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    data = diagnose_why_not_remembered(query=req.query, memory=memory_service, scope=scope, thread_id=req.thread_id)
    return response_object("mase.ui.why_not_remembered", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_why_not_remembered"]
