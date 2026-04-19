"""Tests for the opt-in tri-vault memory layout."""
from __future__ import annotations

import os

import pytest

from mase_tools.memory import tri_vault


@pytest.fixture()
def tri_env(tmp_path, monkeypatch):
    monkeypatch.setenv(tri_vault.LAYOUT_ENV, "tri")
    monkeypatch.setenv(tri_vault.VAULT_ENV, str(tmp_path / "memory"))
    return tmp_path / "memory"


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv(tri_vault.LAYOUT_ENV, raising=False)
    assert not tri_vault.is_enabled()
    assert tri_vault.ensure_layout() == {}
    assert tri_vault.write_bucket("context", "anything", {"x": 1}) is None
    assert tri_vault.list_bucket("state") == []


def test_ensure_layout_creates_three_buckets(tri_env):
    paths = tri_vault.ensure_layout()
    assert set(paths) == {"context", "sessions", "state"}
    for p in paths.values():
        assert p.is_dir()
    assert (tri_env / "README.md").exists()


def test_write_read_roundtrip(tri_env):
    tri_vault.write_bucket("context", "user_prefs", {"language": "zh"})
    out = tri_vault.read_bucket("context", "user_prefs")
    assert out["value"] == {"language": "zh"}
    assert "updated_at" in out


def test_unknown_bucket_rejected(tri_env):
    with pytest.raises(ValueError):
        tri_vault.write_bucket("nonsense", "k", "v")


def test_path_traversal_keys_are_neutralized(tri_env):
    target = tri_vault.write_bucket("state", "../../../escape", {"x": 1})
    paths = tri_vault.ensure_layout()
    assert target.parent == paths["state"], "key must not escape its bucket"


def test_list_bucket_returns_keys(tri_env):
    tri_vault.write_bucket("sessions", "2026-04-19", {"turn": 1})
    tri_vault.write_bucket("sessions", "2026-04-20", {"turn": 2})
    keys = tri_vault.list_bucket("sessions")
    assert keys == ["2026-04-19", "2026-04-20"]
