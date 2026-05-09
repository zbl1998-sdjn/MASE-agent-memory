"""
OpenAI-compatible Chat Completions API wrapping MASE.

启动:
    python -m integrations.openai_compat.server
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict
from typing import Any

try:
    import uvicorn
    from fastapi import Depends, FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "需要安装: pip install fastapi uvicorn"
    ) from e

from integrations.openai_compat.answer_routes import router as answer_router
from integrations.openai_compat.auth_dependencies import (  # noqa: E402
    is_read_only_mode,
    require_internal_api_key,
    require_writable_mode,
)
from integrations.openai_compat.cost_routes import (
    router as cost_router,
)
from integrations.openai_compat.diagnostic_routes import (
    router as diagnostic_router,
)
from integrations.openai_compat.drift_routes import (
    router as drift_router,
)
from integrations.openai_compat.golden_routes import (
    router as golden_router,
)
from integrations.openai_compat.governance_routes import (
    router as governance_router,
)
from integrations.openai_compat.incident_routes import (
    router as incident_router,
)
from integrations.openai_compat.legacy_exports import *  # noqa: F403
from integrations.openai_compat.lifecycle_routes import (
    router as lifecycle_router,
)
from integrations.openai_compat.memory_routes import (
    router as memory_router,
)
from integrations.openai_compat.observability_routes import (
    quick_actions as _quick_actions,
)
from integrations.openai_compat.observability_routes import (
    router as observability_router,
)
from integrations.openai_compat.privacy_routes import (
    router as privacy_router,
)
from integrations.openai_compat.quality_routes import (
    router as quality_router,
)
from integrations.openai_compat.refusal_routes import (
    router as refusal_router,
)
from integrations.openai_compat.repair_routes import (
    router as repair_router,
)
from integrations.openai_compat.replay_routes import (
    router as replay_router,
)
from integrations.openai_compat.responses import (  # noqa: E402
    response_object as _response_object,
)
from integrations.openai_compat.runtime import FRONTEND_DIST, SERVER_CONFIG_PATH, memory_service  # noqa: E402
from integrations.openai_compat.schemas import (
    ChatCompletionRequest,
    ChatMessage,
    MaseRunRequest,
)
from integrations.openai_compat.slo_routes import router as slo_router
from integrations.openai_compat.trace_routes import (
    router as trace_router,
)
from mase import describe_models, mase_ask, mase_run
from mase.audit_log import append_audit_event
from mase.auth_policy import AuthContext, default_auth_context, read_internal_api_key
from mase_tools.memory.db_core import PROFILE_TEMPLATES

logger = logging.getLogger("mase.openai_compat")


class RequestBodyTooLargeError(Exception):
    pass


def _configured_max_request_body_bytes() -> int:
    raw = os.environ.get("MASE_MAX_REQUEST_BODY_BYTES", "262144").strip()
    if not raw:
        return 262144
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning("Invalid MASE_MAX_REQUEST_BODY_BYTES=%r; using 262144", raw)
        return 262144
    return max(1024, min(parsed, 1024 * 1024))


class RequestBodySizeLimitMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = _configured_max_request_body_bytes()
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length.decode("ascii")) > limit:
                    await JSONResponse({"detail": "request_body_too_large"}, status_code=413)(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestBodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLargeError:
            await JSONResponse({"detail": "request_body_too_large"}, status_code=413)(scope, receive, send)


_is_read_only_mode = is_read_only_mode


def _configured_port() -> int:
    raw = os.environ.get("MASE_PLATFORM_PORT", "8765").strip()
    try:
        port = int(raw)
    except ValueError:
        logger.warning("Invalid MASE_PLATFORM_PORT=%r; using 8765", raw)
        return 8765
    return max(1, min(port, 65535))


def _configured_host() -> str:
    return os.environ.get("MASE_PLATFORM_HOST", "127.0.0.1").strip() or "127.0.0.1"


app = FastAPI(title="MASE OpenAI-Compatible API")
app.add_middleware(RequestBodySizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cost_router)
app.include_router(answer_router)
app.include_router(diagnostic_router)
app.include_router(drift_router)
app.include_router(golden_router)
app.include_router(governance_router)
app.include_router(incident_router)
app.include_router(lifecycle_router)
app.include_router(memory_router)
app.include_router(observability_router)
app.include_router(privacy_router)
app.include_router(quality_router)
app.include_router(repair_router)
app.include_router(refusal_router)
app.include_router(replay_router)
app.include_router(slo_router)
app.include_router(trace_router)


def _last_user(msgs: list[ChatMessage]) -> str:
    for m in reversed(msgs):
        if m.role == "user":
            return m.content
    return ""


def _auth_for_audit(auth: Any) -> AuthContext:
    return auth if isinstance(auth, AuthContext) else default_auth_context()


def _audit_success(
    auth: Any,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    scope: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    context = _auth_for_audit(auth)
    append_audit_event(
        actor_id=context.actor_id,
        role=context.role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        scope=scope,
        metadata=metadata,
    )


def _trace_to_dict(trace: Any) -> dict[str, Any]:
    return {
        "schema_version": "mase.trace.v1",
        "trace_id": trace.trace_id,
        "route": asdict(trace.route),
        "planner": trace.planner.to_dict(),
        "thread": trace.thread.to_dict(),
        "executor_target": trace.executor_target,
        "answer": trace.answer,
        "search_results": trace.search_results,
        "fact_sheet": trace.fact_sheet,
        "evidence_assessment": trace.evidence_assessment,
        "record_path": trace.record_path,
        "steps": trace.steps or [],
    }


def _product_features() -> list[dict[str, str]]:
    return [
        {
            "title": "White-box memory",
            "description": "SQLite current facts plus event-log evidence, all inspectable and reversible.",
        },
        {
            "title": "Traceable orchestration",
            "description": "Router, notetaker, planner, executor and fact sheet are exposed as an audit chain.",
        },
        {
            "title": "Scope isolation",
            "description": "Tenant, workspace and visibility filters are carried through every product surface.",
        },
        {
            "title": "Production bridge",
            "description": "OpenAI-compatible API and built frontend can be served by one FastAPI process.",
        },
    ]


@app.get("/health")
def health() -> dict[str, Any]:
    validation = memory_service.validate_memory()
    return _response_object(
        "mase.health",
        {"status": "ok", "service": "mase-openai-compat", "version": "0.4.0"},
        validation,
    )


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": "mase",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mase",
            }
        ],
    }


@app.get("/v1/ui/bootstrap")
def ui_bootstrap() -> dict[str, Any]:
    validation = memory_service.validate_memory()
    return _response_object(
        "mase.ui.bootstrap",
        {
            "profile_templates": PROFILE_TEMPLATES,
            "models": describe_models(config_path=SERVER_CONFIG_PATH),
            "validation": validation,
            "product": {
                "name": "MASE Memory Platform",
                "tagline": "White-box memory operations for LLM agents",
                "features": _product_features(),
                "quick_actions": _quick_actions(),
                "frontend_static_ready": (FRONTEND_DIST / "index.html").exists(),
                "auth_required": read_internal_api_key() is not None,
                "read_only": _is_read_only_mode(),
            },
        },
        {"generated_at": int(time.time())},
    )


@app.post("/v1/mase/run")
def run_mase(req: MaseRunRequest, _: None = Depends(require_internal_api_key)) -> dict[str, Any]:
    if req.log:
        require_writable_mode()
    trace = mase_run(req.query, log=req.log)
    return _response_object("mase.trace", _trace_to_dict(trace))


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest) -> Any:
    question = _last_user(req.messages)
    answer = mase_ask(question) if question else ""
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if not req.stream:
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(question),
                "completion_tokens": len(answer),
                "total_tokens": len(question) + len(answer),
            },
        }

    def _stream() -> Any:
        chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": req.model,
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": answer},
                 "finish_reason": None}
            ],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        end = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": req.model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(end, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


if (FRONTEND_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="mase-frontend")


def main() -> None:
    uvicorn.run(app, host=_configured_host(), port=_configured_port())


if __name__ == "__main__":
    main()
