"""Tri-vault memory layout (opt-in via ``MASE_MEMORY_LAYOUT=tri``).

Brain-style three-bucket persistence layered *on top of* the existing SQLite
white-box memory. Activates a directory tree the user can ``git diff`` to see
how memory evolves over time::

    <vault_root>/
        context/   user-stable preferences, profiles, durable facts
        sessions/  rolling per-session conversation snapshots
        state/     ephemeral / scratchpad / in-progress reasoning

Mode is fully opt-in — when ``MASE_MEMORY_LAYOUT`` is unset (the default), this
module is a no-op and MASE behaves exactly as before. When set to ``tri``, MASE
mirrors writes into JSON files under ``$MASE_MEMORY_VAULT`` (defaults to
``<project-root>/memory/``).

Tracked under the ``memory-tri-vault`` publish-blocker.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LAYOUT_ENV = "MASE_MEMORY_LAYOUT"
VAULT_ENV = "MASE_MEMORY_VAULT"
SUPPORTED_LAYOUTS = {"flat", "tri"}
BUCKETS = ("context", "sessions", "state")


def is_enabled() -> bool:
    return os.environ.get(LAYOUT_ENV, "flat").lower() == "tri"


def _vault_root() -> Path:
    raw = os.environ.get(VAULT_ENV)
    if raw:
        return Path(raw).expanduser().resolve()
    raw_runs_dir = os.environ.get("MASE_RUNS_DIR")
    if raw_runs_dir:
        return (Path(raw_runs_dir).expanduser().resolve() / "memory").resolve()
    # Default: <project-root>/memory/
    return (Path(__file__).resolve().parents[2] / "memory").resolve()


def ensure_layout() -> dict[str, Path]:
    """Create the tri-vault directory tree and return the bucket paths.

    Idempotent: safe to call on every startup. No-op if the layout flag is off.
    Returns the mapping ``{"context": …, "sessions": …, "state": …}`` (empty
    dict when disabled).
    """
    if not is_enabled():
        return {}
    root = _vault_root()
    out: dict[str, Path] = {}
    for bucket in BUCKETS:
        p = root / bucket
        p.mkdir(parents=True, exist_ok=True)
        out[bucket] = p
    # Drop a README so an auditor browsing the dir on disk understands what they're looking at.
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# MASE memory vault (tri layout)\n\n"
            "- `context/` — durable user facts, preferences, profiles\n"
            "- `sessions/` — rolling per-session conversation snapshots\n"
            "- `state/`   — ephemeral / scratchpad / in-progress reasoning\n\n"
            "Activated by `MASE_MEMORY_LAYOUT=tri`. Disable by unsetting the env var.\n",
            encoding="utf-8",
        )
    return out


def write_bucket(bucket: str, key: str, value: Any) -> Path | None:
    """Persist ``value`` (JSON-serializable) under ``<vault>/<bucket>/<key>.json``.

    Returns the file path, or ``None`` if tri-vault is disabled.
    """
    if not is_enabled():
        return None
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}; allowed: {BUCKETS}")
    paths = ensure_layout()
    safe_key = key.replace(os.sep, "_").replace("/", "_").replace("\\", "_")
    target = paths[bucket] / f"{safe_key}.json"
    payload = {
        "key": key,
        "value": value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def mirror_write(bucket: str, key: str, payload: dict) -> Path | None:
    """Atomically mirror ``payload`` into ``<vault>/<bucket>/<key>.json``.

    Used by the main write path (notetaker, etc.) to keep the on-disk tri-vault
    in sync with the SQLite white-box memory. No-op when tri-vault is disabled,
    so it's safe to call unconditionally from hot paths.

    Atomicity: the JSON is first written to ``<target>.tmp`` and then
    ``os.replace``'d into place so concurrent readers never observe a partial
    file.
    """
    if not is_enabled():
        return None
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}; allowed: {BUCKETS}")
    paths = ensure_layout()
    safe_key = key.replace(os.sep, "_").replace("/", "_").replace("\\", "_")
    target = paths[bucket] / f"{safe_key}.json"
    # Per-write unique tmp name so concurrent writers (multi-CLI, future
    # async FastAPI) don't clobber a shared ``<key>.json.tmp`` mid-flight,
    # which would corrupt JSON or break os.replace with FileNotFoundError.
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    body = {
        "key": key,
        "payload": payload,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Per-target lock serialises the os.replace step within a single process.
    # Windows MoveFileExW raises PermissionError if two threads try to replace
    # the same destination simultaneously; this lock removes that race for
    # the in-process case (multi-process writers should set MASE_VAULT_FLOCK=1
    # and use a future fcntl/msvcrt lock — out of scope for this fix).
    lock = _target_lock(target)
    with lock:
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        # Retry os.replace up to 3 times for Windows transient I/O contention
        # (AV scanners, indexers, sibling processes momentarily holding the
        # destination open). 50ms back-off is well below human-perceptible.
        last_err: BaseException | None = None
        for attempt in range(3):
            try:
                os.replace(tmp, target)
                last_err = None
                break
            except (PermissionError, OSError) as exc:
                last_err = exc
                time.sleep(0.05 * (attempt + 1))
        if last_err is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise last_err
    return target


_TARGET_LOCKS: dict[str, threading.Lock] = {}
_TARGET_LOCKS_GUARD = threading.Lock()


def _target_lock(target: Path) -> threading.Lock:
    key = str(target)
    with _TARGET_LOCKS_GUARD:
        lock = _TARGET_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _TARGET_LOCKS[key] = lock
        return lock


def read_bucket(bucket: str, key: str) -> Any | None:
    if not is_enabled():
        return None
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}; allowed: {BUCKETS}")
    paths = ensure_layout()
    safe_key = key.replace(os.sep, "_").replace("/", "_").replace("\\", "_")
    target = paths[bucket] / f"{safe_key}.json"
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def list_bucket(bucket: str) -> list[str]:
    if not is_enabled():
        return []
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}; allowed: {BUCKETS}")
    paths = ensure_layout()
    return sorted(p.stem for p in paths[bucket].glob("*.json"))


__all__ = [
    "BUCKETS",
    "LAYOUT_ENV",
    "VAULT_ENV",
    "ensure_layout",
    "is_enabled",
    "list_bucket",
    "mirror_write",
    "read_bucket",
    "write_bucket",
]
