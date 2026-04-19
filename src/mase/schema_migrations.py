"""Schema migrations for the MASE SQLite memory database.

Today the schema is created in-place by ``BenchmarkNotetaker._init_db``.
That works but offers no path to evolve the schema (add columns, indexes,
new tables) on existing memory dbs without manual SQL.

This module gives us a tiny migration runner with a single ``schema_version``
table.  Each migration is a function that takes a sqlite connection and runs
DDL.  Future contributors only edit :data:`MIGRATIONS` — they never touch
production data manually.

Migrations are idempotent and safe to call on every startup; the runner
short-circuits when ``schema_version`` already equals the latest migration's
version.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


def _v1_baseline(conn: sqlite3.Connection) -> None:
    """Baseline matching what BenchmarkNotetaker creates today."""
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
    _ensure_version_table(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def latest_version() -> int:
    return max((m[0] for m in MIGRATIONS), default=0)


def migrate(db_path: str | Path) -> dict[str, int]:
    """Apply all pending migrations.  Returns ``{"from": old, "to": new}``."""
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        try:
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
