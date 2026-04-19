"""Wire-up test for tri_vault.mirror_write through NotetakerAgent.

Confirms the previously-dead tri_vault module is now exercised by the main
notetaker write path when ``MASE_MEMORY_LAYOUT=tri``.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mase_tools.memory import db_core, tri_vault
from src.mase.notetaker_agent import NotetakerAgent


@pytest.fixture()
def tri_env(tmp_path, monkeypatch):
    monkeypatch.setenv(tri_vault.LAYOUT_ENV, "tri")
    monkeypatch.setenv(tri_vault.VAULT_ENV, str(tmp_path / "memory"))
    db_path = Path(tempfile.mkdtemp()) / "mem.db"
    monkeypatch.setattr(db_core, "DB_PATH", db_path)
    db_core.init_db()
    return tmp_path / "memory"


def test_mirror_write_appears_when_disabled_default(tmp_path, monkeypatch):
    monkeypatch.delenv(tri_vault.LAYOUT_ENV, raising=False)
    assert tri_vault.mirror_write("sessions", "k", {"x": 1}) is None


def test_notetaker_write_mirrors_to_sessions(tri_env):
    agent = NotetakerAgent()
    tool_call = {
        "function": {
            "name": "mase2_write_interaction",
            "arguments": {
                "thread_id": "t-wire-1",
                "role": "user",
                "content": "hello tri-vault",
            },
        }
    }
    agent.execute_tool_call(tool_call)

    sessions_dir = tri_env / "sessions"
    assert sessions_dir.is_dir(), "tri-vault sessions bucket should exist"
    files = list(sessions_dir.glob("*.json"))
    assert files, f"expected at least one mirrored JSON in {sessions_dir}"
    assert any("t-wire-1" in p.name for p in files)


def test_notetaker_upsert_mirrors_to_context(tri_env):
    agent = NotetakerAgent()
    tool_call = {
        "function": {
            "name": "mase2_upsert_fact",
            "arguments": {
                "category": "user_preferences",
                "key": "language",
                "value": "zh",
            },
        }
    }
    agent.execute_tool_call(tool_call)
    context_dir = tri_env / "context"
    files = list(context_dir.glob("*.json"))
    assert files, "expected upsert_fact to mirror into context bucket"
