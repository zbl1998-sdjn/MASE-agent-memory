from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuthContext:
    actor_id: str
    role: str
    permissions: tuple[str, ...]


class AuthUnauthorized(Exception):
    pass


ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "viewer": ("read",),
    "operator": ("read", "write", "repair"),
    "repair_approver": ("read", "write", "repair", "repair_approve"),
    "admin": ("read", "write", "repair", "repair_approve", "pricing", "audit", "export", "admin"),
    "auditor": ("read", "audit", "export", "pricing"),
}


def read_internal_api_key() -> str | None:
    value = os.environ.get("MASE_INTERNAL_API_KEY", "").strip()
    return value or None


def permissions_for_role(role: str) -> tuple[str, ...]:
    normalized = str(role or "viewer").strip().lower()
    return ROLE_PERMISSIONS.get(normalized, ROLE_PERMISSIONS["viewer"])


def default_auth_context() -> AuthContext:
    role = os.environ.get("MASE_DEFAULT_ROLE", "admin").strip().lower() or "admin"
    if role not in ROLE_PERMISSIONS:
        role = "viewer"
    actor_id = os.environ.get("MASE_DEFAULT_ACTOR_ID", "local-dev").strip() or "local-dev"
    return AuthContext(actor_id=actor_id, role=role, permissions=permissions_for_role(role))


def _context_from_token_payload(token: str, payload: Any) -> AuthContext:
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
    return AuthContext(actor_id=actor_id or f"token:{token[:6]}", role=role, permissions=permissions_for_role(role))


def configured_token_contexts() -> dict[str, AuthContext]:
    contexts: dict[str, AuthContext] = {}
    expected = read_internal_api_key()
    if expected:
        contexts[expected] = default_auth_context()
    raw = os.environ.get("MASE_API_KEYS_JSON", "").strip()
    if not raw:
        return contexts
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
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
    return bool(configured_token_contexts())


def resolve_auth_context(
    provided_token: str | None,
    *,
    requested_role: str | None = None,
    requested_actor: str | None = None,
) -> AuthContext:
    contexts = configured_token_contexts()
    if not contexts:
        return default_auth_context()
    if not provided_token:
        raise AuthUnauthorized
    for token, context in contexts.items():
        if secrets.compare_digest(provided_token, token):
            role = str(requested_role or "").strip().lower()
            if token == read_internal_api_key() and role in ROLE_PERMISSIONS:
                actor_id = str(requested_actor or context.actor_id).strip() or context.actor_id
                return AuthContext(actor_id=actor_id, role=role, permissions=permissions_for_role(role))
            return context
    raise AuthUnauthorized


def has_permission(context: AuthContext, permission: str) -> bool:
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
