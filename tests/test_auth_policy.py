from __future__ import annotations

import json

import pytest

from mase.auth_policy import AuthUnauthorized, has_permission, resolve_auth_context


def test_resolve_auth_context_supports_internal_key_role_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_INTERNAL_API_KEY", "dev-key")

    context = resolve_auth_context("dev-key", requested_role="auditor", requested_actor="audit-user")

    assert context.actor_id == "audit-user"
    assert context.role == "auditor"
    assert has_permission(context, "audit")
    assert not has_permission(context, "write")


def test_api_key_mapping_prevents_header_role_escalation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MASE_INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv(
        "MASE_API_KEYS_JSON",
        json.dumps({"viewer-token": {"actor_id": "viewer-user", "role": "viewer"}}),
    )

    context = resolve_auth_context("viewer-token", requested_role="admin", requested_actor="mallory")

    assert context.actor_id == "viewer-user"
    assert context.role == "viewer"
    assert not has_permission(context, "admin")


def test_missing_configured_token_is_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_API_KEYS_JSON", json.dumps({"operator-token": {"role": "operator"}}))
    monkeypatch.delenv("MASE_INTERNAL_API_KEY", raising=False)

    with pytest.raises(AuthUnauthorized):
        resolve_auth_context(None)
