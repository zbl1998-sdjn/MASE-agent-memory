"""双真源读路径切换第一个真实切片(架构①续,2026-07-12,opt-in)。

审计(shadow_read_diff)只做到可见化:哪些 active 治理事实对 legacy
entity_state 读路径不可见(governed_only)。这里把同一份定义接到真实读
路径——MASE_GOVERNED_READ_PATH 开启时,BenchmarkNotetaker._search_entity_state
在 entity_state 结果之后追加这些事实,append-only、按 (category, entity_key)
去重、不占满 entity_state 的名额,默认关闭时零行为(所有既有 benchmark 配置
都没设这个新开关,不受影响)。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "governed_read.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    monkeypatch.delenv("MASE_GOVERNED_READ_PATH", raising=False)
    return db


def _propose_governed_only_fact(category: str, key: str, value: str, *, source: str) -> None:
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    fact = propose_fact(
        FactContract(
            fact_id=new_fact_id(), entity_id="user:t", claim_type="project_fact",
            subject=category, predicate=key, object_value=value,
            confidence=0.9, observed_at="2026-07-12T00:00:00Z",
        ),
        source, source_type="chat", source_id="m1", trust_level=3, source_full_text=source,
    )
    assert fact.status == "active"


class TestDefaultOff:
    def test_governed_only_fact_invisible_by_default(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        _propose_governed_only_fact(
            "finance_budget", "phoenix_budget", "8000 元", source="会议记录:凤凰项目预算定为 8000 元。"
        )
        from mase.benchmark_notetaker import BenchmarkNotetaker

        bn = BenchmarkNotetaker()
        results = bn._search_entity_state(["phoenix_budget"], limit=5)
        assert results == []


class TestEnabledSupplement:
    def test_governed_only_fact_becomes_visible(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_GOVERNED_READ_PATH", "1")
        _propose_governed_only_fact(
            "finance_budget", "phoenix_budget", "8000 元", source="会议记录:凤凰项目预算定为 8000 元。"
        )
        from mase.benchmark_notetaker import BenchmarkNotetaker

        bn = BenchmarkNotetaker()
        results = bn._search_entity_state(["phoenix_budget"], limit=5)
        assert len(results) == 1
        row = results[0]
        assert row["category"] == "finance_budget"
        assert row["entity_key"] == "phoenix_budget"
        assert row["entity_value"] == "8000 元"
        assert row["_source"] == "governed_fact"
        assert row["confidence"] == "high"
        assert row["retrieval_reason"] == "governed_only_fact"

    def test_dual_written_fact_is_not_duplicated(self, tmp_path, monkeypatch):
        """entity_state 已有同 (category, key) 行时,不重复追加治理事实。"""
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_GOVERNANCE_DUAL_WRITE", "1")
        monkeypatch.setenv("MASE_GOVERNED_READ_PATH", "1")
        import re

        from mase_tools.memory.api import mase2_upsert_fact, mase2_write_interaction

        msg = mase2_write_interaction("t1", "user", "记录:owner 为 Alice。")
        log_id = int(re.search(r"ID (\d+)", msg).group(1))
        mase2_upsert_fact("project_status", "owner", "Alice", reason="user stated", source_log_id=log_id)

        from mase.benchmark_notetaker import BenchmarkNotetaker

        bn = BenchmarkNotetaker()
        results = bn._search_entity_state(["owner"], limit=5)
        assert len(results) == 1
        assert results[0]["_source"] == "entity_state"

    def test_supplement_never_displaces_entity_state_rows(self, tmp_path, monkeypatch):
        """entity_state 结果已经占满 limit 时,不追加治理事实(不抢 legacy 名额)。"""
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_GOVERNANCE_DUAL_WRITE", "1")
        monkeypatch.setenv("MASE_GOVERNED_READ_PATH", "1")
        import re

        from mase_tools.memory.api import mase2_upsert_fact, mase2_write_interaction

        msg = mase2_write_interaction("t1", "user", "记录:budget 为 100。")
        log_id = int(re.search(r"ID (\d+)", msg).group(1))
        mase2_upsert_fact("finance_budget", "budget", "100", reason="user stated", source_log_id=log_id)
        _propose_governed_only_fact(
            "finance_budget", "budget_extra", "200", source="会议记录:budget_extra 定为 200。"
        )

        from mase.benchmark_notetaker import BenchmarkNotetaker

        bn = BenchmarkNotetaker()
        results = bn._search_entity_state(["budget"], limit=1)
        assert len(results) == 1
        assert results[0]["_source"] == "entity_state"

    def test_no_terms_returns_empty(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_GOVERNED_READ_PATH", "1")
        from mase.governance.write_facade import governed_only_supplement_rows

        assert governed_only_supplement_rows([], limit=5, db_path=str(tmp_path / "governed_read.db")) == []
