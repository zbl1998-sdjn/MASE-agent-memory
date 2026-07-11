"""后台任务持久队列(架构切片②,2026-07-12)。

派生任务(写入时抽取/GC/未来的自动巩固)此前是裸 daemon 线程 + atexit
drain:进程崩溃任务即丢、无重试、无留痕。本模块把任务落库(``pending_jobs``
additive 表),执行语义:

- ``enqueue``:显式 ``job_id`` 时幂等(重复入队被忽略),否则自动生成;
- ``run_pending``:按 created_at 逐个取 pending → running → handler 执行 →
  done;handler 抛异常 → attempts+1,未达 ``max_attempts`` 回 pending 可重试,
  达上限标 failed 不再取(失败面显式,不静默);
- ``recover_stale_running``:进程崩溃遗留的 running 行复位回 pending
  (attempts 保留)——engine 启动时调用,纯 SQL 快速;
- 消费仍在调用方的后台线程里进行,但任务生死与进程解耦。

派生任务失败不得反向破坏主链路(与 _gc_worker 同语义),handler 内部异常
由队列吞并记入 last_error。
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from .contracts.fact_contract import utc_now

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


def enqueue(
    job_type: str,
    payload: dict[str, Any],
    *,
    job_id: str | None = None,
    max_attempts: int = 3,
    db_path: str | Path | None = None,
) -> str:
    """入队一个任务;显式 job_id 幂等(已存在则忽略),返回 job_id。"""
    job_id = job_id or f"job_{uuid.uuid4().hex}"
    now = utc_now()
    with closing(get_connection(db_path)) as conn, conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO pending_jobs
                (job_id, job_type, payload_json, status, attempts, max_attempts, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (job_id, job_type, json.dumps(payload, ensure_ascii=False), max_attempts, now, now),
        )
    return job_id


def recover_stale_running(*, db_path: str | Path | None = None) -> int:
    """崩溃遗留的 running 行复位回 pending(attempts 保留);返回复位数。"""
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.execute(
            "UPDATE pending_jobs SET status = 'pending', updated_at = ? WHERE status = 'running'",
            (utc_now(),),
        )
        return int(cursor.rowcount or 0)


def run_pending(
    handlers: dict[str, Callable[[dict[str, Any]], Any]],
    *,
    limit: int | None = None,
    db_path: str | Path | None = None,
) -> dict[str, int]:
    """消费 pending 任务;返回 {done, failed_retryable, failed_terminal, no_handler} 计数。

    单消费者语义:每个任务先原子置 running 再执行(多 worker 同时 run_pending
    时靠该状态位互斥;本切片以单 worker 为设计目标,多写者争用见架构③压测)。
    消费的是调用时刻的 pending 快照:本轮失败回 pending 的任务不在本轮内
    立即重试(重试留给下次触发,避免失败 job 在一次消费里空转烧光尝试数)。
    """
    report = {"done": 0, "failed_retryable": 0, "failed_terminal": 0, "no_handler": 0}
    with closing(get_connection(db_path)) as conn:
        snapshot = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM pending_jobs WHERE status = 'pending' ORDER BY created_at, job_id"
            ).fetchall()
        ]
    for row in snapshot:
        if limit is not None and sum(report.values()) >= limit:
            break
        with closing(get_connection(db_path)) as conn, conn:
            claimed = conn.execute(
                "UPDATE pending_jobs SET status = 'running', updated_at = ? "
                "WHERE job_id = ? AND status = 'pending'",
                (utc_now(), row["job_id"]),
            ).rowcount
        if not claimed:
            continue  # 被并发 worker 抢走
        job_id = str(row["job_id"])
        job_type = str(row["job_type"])
        payload = json.loads(str(row["payload_json"]))
        attempts = int(row["attempts"]) + 1
        max_attempts = int(row["max_attempts"])

        handler = handlers.get(job_type)
        if handler is None:
            _finish(job_id, FAILED, attempts, f"no handler for job_type={job_type!r}", db_path)
            report["no_handler"] += 1
            continue
        try:
            handler(payload)
        except Exception as exc:  # noqa: BLE001 - 派生任务失败入队记录,不破坏主链路
            error = f"{type(exc).__name__}: {exc}"
            if attempts >= max_attempts:
                _finish(job_id, FAILED, attempts, error, db_path)
                report["failed_terminal"] += 1
            else:
                _finish(job_id, PENDING, attempts, error, db_path)
                report["failed_retryable"] += 1
            continue
        _finish(job_id, DONE, attempts, None, db_path)
        report["done"] += 1
    return report


def _finish(job_id: str, status: str, attempts: int, error: str | None, db_path: str | Path | None) -> None:
    with closing(get_connection(db_path)) as conn, conn:
        conn.execute(
            "UPDATE pending_jobs SET status = ?, attempts = ?, last_error = ?, updated_at = ? WHERE job_id = ?",
            (status, attempts, error, utc_now(), job_id),
        )


__all__ = [
    "DONE",
    "FAILED",
    "PENDING",
    "RUNNING",
    "enqueue",
    "recover_stale_running",
    "run_pending",
]
