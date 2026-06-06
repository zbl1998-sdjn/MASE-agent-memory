"""本地 API/维修操作使用的轻量鉴权与权限策略。"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuthContext:
    """一次请求解析后的操作者身份和权限集合。"""

    actor_id: str
    role: str
    permissions: tuple[str, ...]


class AuthUnauthorized(Exception):
    """请求未提供有效 token 时抛出的鉴权错误。"""

    pass


ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "viewer": ("read",),
    "operator": ("read", "write", "repair"),
    "repair_approver": ("read", "write", "repair", "repair_approve"),
    "admin": ("read", "write", "repair", "repair_approve", "pricing", "audit", "export", "admin"),
    "auditor": ("read", "audit", "export", "pricing"),
}


def read_internal_api_key() -> str | None:
    """读取本地内部 API key；空字符串视为未配置。"""
    value = os.environ.get("MASE_INTERNAL_API_KEY", "").strip()
    return value or None


def permissions_for_role(role: str) -> tuple[str, ...]:
    """把角色名映射为权限；未知角色降级为 viewer。"""
    normalized = str(role or "viewer").strip().lower()
    return ROLE_PERMISSIONS.get(normalized, ROLE_PERMISSIONS["viewer"])


def default_auth_context() -> AuthContext:
    """未配置 token 时的本地开发默认身份。"""
    role = os.environ.get("MASE_DEFAULT_ROLE", "admin").strip().lower() or "admin"
    if role not in ROLE_PERMISSIONS:
        role = "viewer"
    actor_id = os.environ.get("MASE_DEFAULT_ACTOR_ID", "local-dev").strip() or "local-dev"
    return AuthContext(actor_id=actor_id, role=role, permissions=permissions_for_role(role))


def _context_from_token_payload(token: str, payload: Any) -> AuthContext:
    """把 MASE_API_KEYS_JSON 中的 token payload 解析成 AuthContext。"""
    if isinstance(payload, str):
        actor_id = payload
        role = "viewer"
    elif isinstance(payload, dict):
        actor_id = str(payload.get("actor_id") or payload.get("actor") or "api-user")
        role = str(payload.get("role") or "viewer").strip().lower()
    else:
        actor_id = "api-user"
        role = "viewer"
    if role not in ROLE_PERMISSIONS:
        role = "viewer"
    # actor_id 缺失时只暴露 token 前缀，不泄漏完整 token。
    return AuthContext(actor_id=actor_id or f"token:{token[:6]}", role=role, permissions=permissions_for_role(role))


def configured_token_contexts() -> dict[str, AuthContext]:
    """读取所有已配置 token 及其上下文。"""
    contexts: dict[str, AuthContext] = {}
    expected = read_internal_api_key()
    if expected:
        # MASE_INTERNAL_API_KEY 继承默认上下文，便于本地单 key 部署。
        contexts[expected] = default_auth_context()
    raw = os.environ.get("MASE_API_KEYS_JSON", "").strip()
    if not raw:
        return contexts
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # 配置错误时不抛异常，保持系统可启动；调用方会看到未配置额外 token。
        return contexts
    if not isinstance(payload, dict):
        return contexts
    entries = payload.get("tokens", payload)
    if isinstance(entries, list):
        for item in entries:
            if isinstance(item, dict) and (token := str(item.get("token") or "").strip()):
                contexts[token] = _context_from_token_payload(token, item)
    elif isinstance(entries, dict):
        for token, item in entries.items():
            token_text = str(token).strip()
            if token_text:
                contexts[token_text] = _context_from_token_payload(token_text, item)
    return contexts


def has_configured_tokens() -> bool:
    """判断是否存在任何显式 token。"""
    return bool(configured_token_contexts())


def resolve_auth_context(
    provided_token: str | None,
    *,
    requested_role: str | None = None,
    requested_actor: str | None = None,
) -> AuthContext:
    """根据提供的 token 解析 AuthContext。"""
    contexts = configured_token_contexts()
    if not contexts:
        # 本地开发默认不强制 token；一旦配置 token，就进入严格鉴权。
        return default_auth_context()
    if not provided_token:
        raise AuthUnauthorized
    for token, context in contexts.items():
        if secrets.compare_digest(provided_token, token):
            role = str(requested_role or "").strip().lower()
            if token == read_internal_api_key() and role in ROLE_PERMISSIONS:
                # 只有内部 key 可请求角色覆盖，普通 API token 固定使用配置角色。
                actor_id = str(requested_actor or context.actor_id).strip() or context.actor_id
                return AuthContext(actor_id=actor_id, role=role, permissions=permissions_for_role(role))
            return context
    raise AuthUnauthorized


def has_permission(context: AuthContext, permission: str) -> bool:
    """检查上下文是否具备单个权限。"""
    return permission in context.permissions


__all__ = [
    "AuthContext",
    "AuthUnauthorized",
    "ROLE_PERMISSIONS",
    "configured_token_contexts",
    "default_auth_context",
    "has_configured_tokens",
    "has_permission",
    "permissions_for_role",
    "read_internal_api_key",
    "resolve_auth_context",
]
