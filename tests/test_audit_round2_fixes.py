"""Lock-in tests for the 2026-04 round-2 audit fixes.

Audit found three latent concurrency / lifecycle bugs:
- P1 ghost GC: daemon thread killed on CLI exit before LLM call finishes
- P2 tri_vault race: hardcoded ``<key>.json.tmp`` collides under concurrent writes
- P3 env-var pollution: ModelInterface.__init__ unconditionally writes os.environ
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# P2: tri_vault.mirror_write must use a per-call unique tmp filename.
# ---------------------------------------------------------------------------
def test_tri_vault_mirror_write_uses_unique_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("MASE_MEMORY_LAYOUT", "tri")
    monkeypatch.setenv("MASE_MEMORY_VAULT", str(tmp_path))

    from mase_tools.memory import tri_vault

    captured_tmp_names: list[str] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        captured_tmp_names.append(Path(src).name)
        return real_replace(src, dst)

    with patch.object(os, "replace", side_effect=spy_replace):
        tri_vault.mirror_write("sessions", "thread-A", {"x": 1})
        tri_vault.mirror_write("sessions", "thread-A", {"x": 2})

    # Two calls to the SAME key must have produced TWO DIFFERENT tmp names.
    assert len(captured_tmp_names) == 2
    assert captured_tmp_names[0] != captured_tmp_names[1], (
        f"tri_vault mirror_write reused tmp name; race vulnerable: {captured_tmp_names}"
    )
    # Both should still be tmp-suffixed.
    for n in captured_tmp_names:
        assert n.endswith(".tmp"), n


def test_tri_vault_concurrent_writes_no_collision(tmp_path, monkeypatch):
    monkeypatch.setenv("MASE_MEMORY_LAYOUT", "tri")
    monkeypatch.setenv("MASE_MEMORY_VAULT", str(tmp_path))

    from mase_tools.memory import tri_vault

    errors: list[BaseException] = []

    def writer(i: int):
        try:
            for j in range(20):
                tri_vault.mirror_write("sessions", "shared-key", {"i": i, "j": j})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent mirror_write raised: {errors}"
    # Final file should be valid JSON, not corrupted.
    target = tmp_path / "sessions" / "shared-key.json"
    assert target.exists()
    import json
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body["key"] == "shared-key"


# ---------------------------------------------------------------------------
# P3: ModelInterface must not clobber a pre-existing MASE_CONFIG_PATH env var.
# ---------------------------------------------------------------------------
def test_model_interface_does_not_clobber_existing_env(monkeypatch, tmp_path):
    sentinel = str(tmp_path / "user_supplied_config.json")
    monkeypatch.setenv("MASE_CONFIG_PATH", sentinel)

    real_cfg = tmp_path / "other_config.json"
    real_cfg.write_text('{"agents": {}, "models": {}}', encoding="utf-8")

    from src.mase.model_interface import ModelInterface

    with patch("src.mase.model_interface.resolve_config_path", return_value=real_cfg):
        ModelInterface()

    assert os.environ["MASE_CONFIG_PATH"] == sentinel, (
        "ModelInterface clobbered a user-set MASE_CONFIG_PATH; "
        "background threads doing this is a thread-safety hazard."
    )


def test_model_interface_does_not_set_env_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MASE_CONFIG_PATH", raising=False)

    cfg = tmp_path / "x.json"
    cfg.write_text('{"agents": {}, "models": {}}', encoding="utf-8")

    from src.mase.model_interface import ModelInterface

    with patch("src.mase.model_interface.resolve_config_path", return_value=cfg):
        ModelInterface()

    assert os.environ.get("MASE_CONFIG_PATH") is None


def test_model_interface_env_file_does_not_set_config_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MASE_CONFIG_PATH", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("MASE_CONFIG_PATH=should-not-leak.json\n", encoding="utf-8")
    cfg = tmp_path / "config.json"
    cfg.write_text(
        '{"agents": {}, "models": {}, "env_file": ".env"}',
        encoding="utf-8",
    )

    from src.mase.model_interface import ModelInterface

    ModelInterface(cfg)

    assert os.environ.get("MASE_CONFIG_PATH") is None


def test_mase_system_does_not_set_config_env_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MASE_CONFIG_PATH", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "memory.sqlite3"))

    cfg = tmp_path / "config.json"
    cfg.write_text(
        """
        {
          "models": {
            "router": {"provider": "ollama", "model_name": "router-test"},
            "notetaker": {"provider": "ollama", "model_name": "notetaker-test"},
            "planner": {"provider": "ollama", "model_name": "planner-test"},
            "executor": {"provider": "ollama", "model_name": "executor-test"}
          },
          "memory": {"json_dir": "memory", "log_dir": "logs", "index_db": "memory/index.db"}
        }
        """,
        encoding="utf-8",
    )

    from src.mase.engine import MASESystem

    MASESystem(cfg)

    assert os.environ.get("MASE_CONFIG_PATH") is None


# ---------------------------------------------------------------------------
# P1: MASESystem must expose a join_background_tasks() drain.
# ---------------------------------------------------------------------------
def test_mase_system_exposes_gc_drain():
    from src.mase.engine import MASESystem

    assert hasattr(MASESystem, "join_background_tasks"), (
        "MASESystem missing join_background_tasks — daemon GC threads will be reaped on CLI exit."
    )
    assert hasattr(MASESystem, "_atexit_drain"), (
        "MASESystem missing _atexit_drain — atexit hook not wired."
    )


def test_join_background_tasks_handles_empty_list():
    """The drain helper must be a safe no-op when GC was never used."""
    from src.mase.engine import MASESystem

    instance = MASESystem.__new__(MASESystem)  # bypass __init__ (needs config.json)
    instance._gc_threads = []
    assert instance.join_background_tasks(timeout=0.1) == 0
