"""Service hardening primitives for governance sidecar mode(P6).

这些工具是可测试的本地原语:写入串行化、幂等键、限流、备份/恢复、
namespace key 与本地 trace event。它们不替代外部网关/OTel collector,但
提供 sidecar 服务化前必须有的 fail-closed 基础行为。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing
from pathlib import Path
from typing import Any, TypeVar

from mase_tools.memory.db_core import get_connection, resolve_db_path

from .fact_contract import utc_now

T = TypeVar("T")


class GovernanceWriteQueue:
    """单 worker 串行写队列;调用方通过 timeout 防止无界等待。"""

    def __init__(self, *, name: str = "governance-write") -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)

    def run(self, operation: Callable[..., T], *args: Any, timeout: float = 5.0, **kwargs: Any) -> T:
        """Run one governance write operation with a bounded wait."""
        future = self._executor.submit(operation, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise TimeoutError(f"governance write timed out after {timeout}s") from None

    def close(self) -> None:
        """Shut down the worker and cancel queued writes."""
        self._executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self) -> GovernanceWriteQueue:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def namespace_key(
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> str:
    """多租户隔离用确定性 namespace key。"""
    return "|".join((tenant_id or "", workspace_id or "", visibility or "private"))


def operation_hash(payload: Any) -> str:
    """幂等键绑定的稳定 payload hash。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_idempotency_key(
    key: str,
    op_hash: str,
    *,
    result: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """登记幂等键;重复同 hash 返回 replay,不同 hash 返回 conflict。"""
    now = utc_now()
    with closing(get_connection(db_path)) as conn, conn:
        _ensure_hardening_schema(conn)
        row = conn.execute(
            "SELECT operation_hash, result_json, created_at FROM governance_idempotency WHERE key = ?",
            (key,),
        ).fetchone()
        if row is not None:
            stored = _load_json(row["result_json"])
            return {
                "accepted": False,
                "replayed": row["operation_hash"] == op_hash,
                "conflict": row["operation_hash"] != op_hash,
                "result": stored,
                "created_at": row["created_at"],
            }
        conn.execute(
            """
            INSERT INTO governance_idempotency (key, operation_hash, result_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, op_hash, json.dumps(result or {}, ensure_ascii=False, sort_keys=True), now),
        )
    return {"accepted": True, "replayed": False, "conflict": False, "result": result or {}, "created_at": now}


def check_rate_limit(
    bucket: str,
    *,
    limit: int,
    window_seconds: int,
    now_epoch: float | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """固定窗口限流;状态持久化到 SQLite,便于多进程重启后 fail-closed。"""
    if limit <= 0:
        return {"allowed": False, "remaining": 0, "reset_at": now_epoch or time.time(), "count": 0}
    now = float(now_epoch if now_epoch is not None else time.time())
    window = max(1, int(window_seconds))
    with closing(get_connection(db_path)) as conn, conn:
        _ensure_hardening_schema(conn)
        row = conn.execute(
            "SELECT count, window_start FROM governance_rate_limits WHERE bucket = ?",
            (bucket,),
        ).fetchone()
        if row is None or now - float(row["window_start"]) >= window:
            count = 1
            window_start = now
        else:
            count = int(row["count"]) + 1
            window_start = float(row["window_start"])
        allowed = count <= limit
        conn.execute(
            """
            INSERT INTO governance_rate_limits (bucket, count, window_start, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bucket) DO UPDATE SET
                count = excluded.count,
                window_start = excluded.window_start,
                updated_at = excluded.updated_at
            """,
            (bucket, count, window_start, utc_now()),
        )
    remaining = max(0, limit - count)
    return {
        "allowed": allowed,
        "remaining": remaining,
        "reset_at": window_start + window,
        "count": count,
    }


def record_governance_trace(
    operation: str,
    *,
    scope: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """记录本地 OTel-style trace event;外部 collector 未配置时也可回放。"""
    trace_id = f"gt_{uuid.uuid4().hex}"
    now = utc_now()
    payload = {
        "trace_id": trace_id,
        "operation": operation,
        "scope": scope or {},
        "metadata": metadata or {},
        "created_at": now,
    }
    with closing(get_connection(db_path)) as conn, conn:
        _ensure_hardening_schema(conn)
        conn.execute(
            """
            INSERT INTO governance_trace_events (trace_id, operation, scope_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                operation,
                json.dumps(payload["scope"], ensure_ascii=False, sort_keys=True),
                json.dumps(payload["metadata"], ensure_ascii=False, sort_keys=True),
                now,
            ),
        )
    return payload


def backup_database(
    destination_dir: str | Path,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """用 SQLite backup API 生成一致性备份并登记 sha256 manifest。"""
    source = _resolve_source_db(db_path)
    destination = Path(destination_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    backup_id = f"backup_{uuid.uuid4().hex}"
    backup_path = destination / f"{source.stem}-{backup_id}.sqlite3"
    with closing(get_connection(source)):
        pass
    src = sqlite3.connect(str(source), timeout=5.0)
    dst = sqlite3.connect(str(backup_path), timeout=5.0)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    checksum = _sha256_file(backup_path)
    manifest = {
        "backup_id": backup_id,
        "source_db": str(source),
        "backup_path": str(backup_path),
        "sha256": checksum,
        "created_at": utc_now(),
    }
    with closing(get_connection(source)) as conn, conn:
        _ensure_hardening_schema(conn)
        conn.execute(
            """
            INSERT INTO governance_backups (backup_id, source_db, backup_path, sha256, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                backup_id,
                manifest["source_db"],
                manifest["backup_path"],
                checksum,
                manifest["created_at"],
            ),
        )
    return manifest


def restore_database(
    backup_path: str | Path,
    target_db_path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """校验 checksum 后恢复到目标路径;调用方负责只在安全窗口执行。"""
    backup = Path(backup_path).expanduser().resolve()
    target = Path(target_db_path).expanduser().resolve()
    checksum = _sha256_file(backup)
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError("backup checksum mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, target)
    with closing(get_connection(target)):
        pass
    return {"restored": True, "target_db": str(target), "sha256": checksum, "restored_at": utc_now()}


def _ensure_hardening_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_idempotency (
            key TEXT PRIMARY KEY,
            operation_hash TEXT NOT NULL,
            result_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_rate_limits (
            bucket TEXT PRIMARY KEY,
            count INTEGER NOT NULL,
            window_start REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_backups (
            backup_id TEXT PRIMARY KEY,
            source_db TEXT NOT NULL,
            backup_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_trace_events (
            trace_id TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _resolve_source_db(db_path: str | Path | None) -> Path:
    if db_path is not None:
        return Path(db_path).expanduser().resolve()
    return resolve_db_path()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
