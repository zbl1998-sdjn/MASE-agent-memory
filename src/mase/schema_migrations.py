"""MASE SQLite 记忆数据库的 schema migration runner。

当前 schema 由 ``BenchmarkNotetaker._init_db`` 就地创建。这样能跑，但无法在不手写
SQL 的前提下演进已有记忆库（新增列、索引、表等）。

本模块提供一个小型 migration runner，通过单独的 ``schema_version`` 表记录版本。
每个 migration 是一个接收 sqlite connection 并执行 DDL 的函数。后续贡献者只编辑
:data:`MIGRATIONS`，不直接手动改生产数据。

Migration 应保持幂等，可在每次启动时调用；当 ``schema_version`` 已达到最新版本时
runner 会直接短路。
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


def _v1_baseline(conn: sqlite3.Connection) -> None:
    """与当前 BenchmarkNotetaker 创建结果一致的 v1 基线。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_query TEXT,
            assistant_response TEXT,
            content TEXT,
            summary TEXT,
            thread_id TEXT,
            thread_label TEXT,
            topic_tokens TEXT,
            metadata TEXT
        )
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts "
        "USING fts5(content, summary, thread_label, tokenize='unicode61')"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_thread_id ON memory_log(thread_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_timestamp ON memory_log(timestamp)")


MIGRATIONS: list[Migration] = [
    (1, "baseline", _v1_baseline),
]


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    """确保 schema_version 表存在。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def current_version(conn: sqlite3.Connection) -> int:
    """读取当前已应用的最高 migration 版本。"""
    _ensure_version_table(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def latest_version() -> int:
    """返回代码中声明的最新 migration 版本。"""
    return max((m[0] for m in MIGRATIONS), default=0)


def migrate(db_path: str | Path) -> dict[str, int]:
    """应用所有待执行 migration，返回 ``{"from": old, "to": new}``。"""
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        try:
            # WAL/busy_timeout 是性能优化；老 SQLite 或只读环境失败时不阻断迁移。
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        old = current_version(conn)
        target = latest_version()
        if old >= target:
            return {"from": old, "to": old}
        for version, name, func in sorted(MIGRATIONS):
            if version <= old:
                continue
            try:
                # 每个 migration 独立事务提交，失败则回滚当前版本。
                func(conn)
                conn.execute(
                    "INSERT INTO schema_version (version, name) VALUES (?, ?)",
                    (version, name),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"from": old, "to": target}
    finally:
        conn.close()


__all__ = ["MIGRATIONS", "current_version", "latest_version", "migrate"]
