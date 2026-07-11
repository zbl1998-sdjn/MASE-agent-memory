"""后台任务持久队列:入队幂等/重试上限/崩溃恢复/消费报告(架构切片②)。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    return db


class TestEnqueueAndRun:
    def test_happy_path_job_runs_and_completes(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.background_jobs import enqueue, run_pending

        seen = []
        enqueue("echo", {"value": 42})
        report = run_pending({"echo": lambda p: seen.append(p)})
        assert seen == [{"value": 42}]
        assert report["done"] == 1

    def test_explicit_job_id_is_idempotent(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.background_jobs import enqueue, run_pending

        seen = []
        enqueue("echo", {"n": 1}, job_id="fixed-1")
        enqueue("echo", {"n": 2}, job_id="fixed-1")  # 重复入队被忽略
        run_pending({"echo": lambda p: seen.append(p)})
        assert seen == [{"n": 1}]

    def test_jobs_run_in_fifo_order(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.background_jobs import enqueue, run_pending

        seen = []
        enqueue("echo", {"n": 1}, job_id="a-first")
        enqueue("echo", {"n": 2}, job_id="b-second")
        run_pending({"echo": lambda p: seen.append(p["n"])})
        assert seen == [1, 2]


class TestFailureSemantics:
    def test_failure_retries_until_max_then_terminal(self, tmp_path, monkeypatch):
        db = _isolate(tmp_path, monkeypatch)
        from mase.background_jobs import enqueue, run_pending

        calls = {"n": 0}

        def _boom(payload):
            calls["n"] += 1
            raise RuntimeError("job down")

        enqueue("boom", {}, job_id="b1", max_attempts=3)
        r1 = run_pending({"boom": _boom})
        assert r1["failed_retryable"] == 1  # attempt 1 → 回 pending
        r2 = run_pending({"boom": _boom})
        assert r2["failed_retryable"] == 1  # attempt 2
        r3 = run_pending({"boom": _boom})
        assert r3["failed_terminal"] == 1  # attempt 3 → failed 终态
        r4 = run_pending({"boom": _boom})
        assert sum(r4.values()) == 0  # failed 不再被取
        assert calls["n"] == 3

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, attempts, last_error FROM pending_jobs WHERE job_id='b1'").fetchone()
        assert row["status"] == "failed" and row["attempts"] == 3
        assert "job down" in row["last_error"]

    def test_missing_handler_is_terminal_failure(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.background_jobs import enqueue, run_pending

        enqueue("unknown_type", {})
        report = run_pending({})
        assert report["no_handler"] == 1


class TestCrashRecovery:
    def test_stale_running_rows_are_recovered(self, tmp_path, monkeypatch):
        db = _isolate(tmp_path, monkeypatch)
        from mase.background_jobs import enqueue, recover_stale_running, run_pending

        enqueue("echo", {"n": 1}, job_id="crashed-job")
        # 模拟崩溃:任务被置 running 后进程死掉
        conn = sqlite3.connect(db)
        conn.execute("UPDATE pending_jobs SET status='running' WHERE job_id='crashed-job'")
        conn.commit()
        conn.close()

        assert run_pending({"echo": lambda p: None}) == {
            "done": 0, "failed_retryable": 0, "failed_terminal": 0, "no_handler": 0,
        }  # running 行不可取
        recovered = recover_stale_running()
        assert recovered == 1
        report = run_pending({"echo": lambda p: None})
        assert report["done"] == 1
