"""FastAPI 鉴权依赖：把 MASE token/角色策略接到 HTTP 路由。"""
from __future__ import annotations

import logging
import os

from fastapi import HTTPException, Request

from mase.audit_log import append_audit_event
from mase.auth_policy import AuthContext, AuthUnauthorized, has_configured_tokens, has_permission, resolve_auth_context

logger = logging.getLogger("mase.openai_compat.auth")
_auth_warning_emitted = False


def is_read_only_mode() -> bool:
    """读取只读模式开关；打开后所有写入依赖都会返回 403。"""
    value = os.environ.get("MASE_READ_ONLY")
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _extract_bearer_or_api_key(request: Request) -> str:
    """同时支持 Authorization: Bearer 和 x-api-key，方便前端/脚本接入。"""
    authorization = request.headers.get("authorization", "")
    bearer_prefix = "Bearer "
    provided = authorization[len(bearer_prefix) :].strip() if authorization.startswith(bearer_prefix) else ""
    return provided or request.headers.get("x-api-key", "").strip()


def get_auth_context(request: Request) -> AuthContext:
    """解析请求身份；失败时映射成 HTTP 401。"""
    try:
        return resolve_auth_context(
            _extract_bearer_or_api_key(request),
            requested_role=request.headers.get("x-mase-role"),
            requested_actor=request.headers.get("x-mase-actor"),
        )
    except AuthUnauthorized:
        raise HTTPException(status_code=401, detail="unauthorized")


def require_writable_mode() -> None:
    """写入端点的第一道开关，优先挡住只读演示环境。"""
    if is_read_only_mode():
        raise HTTPException(status_code=403, detail="read_only_mode")


def require_internal_api_key(request: Request) -> None:
    """旧写入端点的轻量保护：配置 token 后必须带 key。"""
    global _auth_warning_emitted
    if not has_configured_tokens():
        if not _auth_warning_emitted:
            logger.warning("未设置 MASE_INTERNAL_API_KEY；写入端点仅在本地开发态允许无鉴权访问")
            _auth_warning_emitted = True
        return
    get_auth_context(request)


def require_permission(permission: str):
    """生成带审计记录的权限依赖。"""
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
    """组合只读模式检查和 write 权限检查。"""
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
