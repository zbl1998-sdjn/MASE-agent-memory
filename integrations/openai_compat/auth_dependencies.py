from __future__ import annotations

import logging
import os

from fastapi import HTTPException, Request

from mase.audit_log import append_audit_event
from mase.auth_policy import AuthContext, AuthUnauthorized, has_configured_tokens, has_permission, resolve_auth_context

logger = logging.getLogger("mase.openai_compat.auth")
_auth_warning_emitted = False


def is_read_only_mode() -> bool:
    value = os.environ.get("MASE_READ_ONLY")
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _extract_bearer_or_api_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    bearer_prefix = "Bearer "
    provided = authorization[len(bearer_prefix) :].strip() if authorization.startswith(bearer_prefix) else ""
    return provided or request.headers.get("x-api-key", "").strip()


def get_auth_context(request: Request) -> AuthContext:
    try:
        return resolve_auth_context(
            _extract_bearer_or_api_key(request),
            requested_role=request.headers.get("x-mase-role"),
            requested_actor=request.headers.get("x-mase-actor"),
        )
    except AuthUnauthorized:
        raise HTTPException(status_code=401, detail="unauthorized")


def require_writable_mode() -> None:
    if is_read_only_mode():
        raise HTTPException(status_code=403, detail="read_only_mode")


def require_internal_api_key(request: Request) -> None:
    global _auth_warning_emitted
    if not has_configured_tokens():
        if not _auth_warning_emitted:
            logger.warning("MASE_INTERNAL_API_KEY is not set; mutation endpoints are unauthenticated for local dev only")
            _auth_warning_emitted = True
        return
    get_auth_context(request)


def require_permission(permission: str):
    def dependency(request: Request) -> AuthContext:
        context = get_auth_context(request)
        if not has_permission(context, permission):
            append_audit_event(
                actor_id=context.actor_id,
                role=context.role,
                action="auth.permission_denied",
                resource_type="permission",
                resource_id=permission,
                outcome="denied",
                metadata={"path": request.url.path, "method": request.method},
            )
            raise HTTPException(status_code=403, detail=f"forbidden:{permission}")
        return context

    return dependency


def require_write_access(request: Request) -> AuthContext:
    require_writable_mode()
    return require_permission("write")(request)


__all__ = [
    "get_auth_context",
    "is_read_only_mode",
    "require_internal_api_key",
    "require_permission",
    "require_writable_mode",
    "require_write_access",
]
