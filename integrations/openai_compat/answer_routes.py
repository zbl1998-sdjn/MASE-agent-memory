from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_request
from integrations.openai_compat.runtime import memory_service
from integrations.openai_compat.schemas import AnswerSupportRequest
from mase.answer_support import build_answer_support
from mase.auth_policy import AuthContext

router = APIRouter()


@router.post("/v1/ui/answer-support")
def ui_answer_support(
    req: AnswerSupportRequest,
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    evidence = req.evidence
    if evidence is None and req.query:
        keywords = [part for part in req.query.split() if part] or [req.query]
        evidence = memory_service.search_memory(
            keywords,
            full_query=req.query,
            limit=10,
            include_history=True,
            scope_filters=scope,
        )
    data = build_answer_support(req.answer, evidence or [])
    data["query"] = req.query
    data["scope"] = scope
    return response_object("mase.ui.answer_support", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_answer_support"]
