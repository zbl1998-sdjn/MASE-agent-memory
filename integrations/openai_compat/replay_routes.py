from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_request
from integrations.openai_compat.runtime import memory_service
from integrations.openai_compat.schemas import SyntheticReplayRequest
from mase.auth_policy import AuthContext
from mase.synthetic_replay import run_synthetic_replay

router = APIRouter()


@router.post("/v1/ui/synthetic-replay")
def ui_synthetic_replay(
    req: SyntheticReplayRequest,
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    data = run_synthetic_replay(memory_service, req.cases, scope=scope, default_top_k=req.top_k)
    return response_object("mase.ui.synthetic_replay", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_synthetic_replay"]
