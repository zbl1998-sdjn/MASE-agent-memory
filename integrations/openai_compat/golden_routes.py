from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_request
from integrations.openai_compat.runtime import memory_service
from integrations.openai_compat.schemas import GoldenTestsRequest
from mase.auth_policy import AuthContext
from mase.golden_tests import run_golden_tests

router = APIRouter()


@router.post("/v1/ui/golden-tests")
def ui_golden_tests(
    req: GoldenTestsRequest,
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    data = run_golden_tests(memory_service, req.cases, scope=scope, default_top_k=req.top_k)
    return response_object("mase.ui.golden_tests", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_golden_tests"]
