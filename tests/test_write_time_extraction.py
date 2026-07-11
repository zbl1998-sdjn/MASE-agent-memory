"""写入时对话抽取钩子(MASE_WRITE_TIME_EXTRACTION,默认关)。

engine 在 notetaker.write 之后异步触发 project_events(extractor='llm'),
把本会话 user 轮投影为治理 facts——hybrid 注入闭环的写入侧(POC 取证:
oracle 抽取假设下 knowledge-update judge 53.8→74.4,缺的就是写入时抽取)。

契约:
- 默认关:零调用,默认路径行为不变;
- MASE_BENCHMARK_MODE=1 时即使开启也跳过(评测路径不被意外 LLM 抽取污染,
  与 audit-markdown 护栏同先例);
- 幂等增量由 project_events 自带(只扫未投影事件);
- 失败吞掉:投影是派生路径,不得反向破坏主问答链路(_gc_worker 同先例);
- 后台线程挂 _gc_threads,复用 join_background_tasks/atexit drain 基建。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase import engine


def _minimal_system() -> engine.MASESystem:
    system = engine.MASESystem.__new__(engine.MASESystem)
    system.model_interface = object()
    system._gc_threads = []
    return system


class TestSpawnGuards:
    def test_default_off_never_projects(self, monkeypatch):
        monkeypatch.delenv("MASE_WRITE_TIME_EXTRACTION", raising=False)

        def _boom(**kwargs):
            raise AssertionError("default path must not project")

        monkeypatch.setattr("mase.governance.event_projection.project_events", _boom)
        system = _minimal_system()
        system._maybe_spawn_write_time_extraction("t1")
        system.join_background_tasks(timeout=2.0)
        assert system._gc_threads == []

    def test_benchmark_mode_skips_even_when_enabled(self, monkeypatch):
        monkeypatch.setenv("MASE_WRITE_TIME_EXTRACTION", "1")
        monkeypatch.setenv("MASE_BENCHMARK_MODE", "1")

        def _boom(**kwargs):
            raise AssertionError("benchmark mode must not project")

        monkeypatch.setattr("mase.governance.event_projection.project_events", _boom)
        system = _minimal_system()
        system._maybe_spawn_write_time_extraction("t1")
        system.join_background_tasks(timeout=2.0)
        assert system._gc_threads == []


class TestSpawnBehavior:
    def test_enabled_projects_current_thread_with_llm_extractor(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "wte.db"))  # 队列落库,必须隔离
        monkeypatch.setenv("MASE_WRITE_TIME_EXTRACTION", "1")
        monkeypatch.delenv("MASE_BENCHMARK_MODE", raising=False)
        calls: list[dict] = []

        def _capture(**kwargs):
            calls.append(kwargs)
            return {"events_projected": 1}

        monkeypatch.setattr("mase.governance.event_projection.project_events", _capture)
        system = _minimal_system()
        system._maybe_spawn_write_time_extraction("thread-42")
        system.join_background_tasks(timeout=5.0)

        assert len(calls) == 1
        assert calls[0]["thread_id"] == "thread-42"
        assert calls[0]["extractor"] == "llm"
        assert calls[0]["model_interface"] is system.model_interface
        # runtime 写入行是打包形态,不走 dialogue-rows 扫描则恒零产出。
        assert calls[0]["include_dialogue_rows"] is True

    def test_job_is_persisted_and_marked_done(self, tmp_path, monkeypatch):
        """架构切片②:任务先落库(pending_jobs),消费后留 done 痕迹。"""
        monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "wte.db"))
        monkeypatch.setenv("MASE_WRITE_TIME_EXTRACTION", "1")
        monkeypatch.delenv("MASE_BENCHMARK_MODE", raising=False)
        monkeypatch.setattr(
            "mase.governance.event_projection.project_events",
            lambda **kwargs: {"events_projected": 0},
        )
        system = _minimal_system()
        system._maybe_spawn_write_time_extraction("t-persist")
        system.join_background_tasks(timeout=5.0)

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "wte.db"))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT job_type, status FROM pending_jobs").fetchall()
        assert len(rows) == 1
        assert rows[0]["job_type"] == "write_time_extraction"
        assert rows[0]["status"] == "done"

    def test_projection_failure_does_not_break_main_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "wte.db"))  # 队列落库,必须隔离
        monkeypatch.setenv("MASE_WRITE_TIME_EXTRACTION", "1")
        monkeypatch.delenv("MASE_BENCHMARK_MODE", raising=False)

        def _explode(**kwargs):
            raise RuntimeError("llm down")

        monkeypatch.setattr("mase.governance.event_projection.project_events", _explode)
        system = _minimal_system()
        system._maybe_spawn_write_time_extraction("t1")
        # join 正常返回、无异常泄出即通过(派生路径失败不反向破坏)。
        system.join_background_tasks(timeout=5.0)
