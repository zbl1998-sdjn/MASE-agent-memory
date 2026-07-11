"""双真源一致性审计:shadow_read_diff 的漂移检出 + 反向(governed_only)对照。

架构收敛第一切片(2026-07-12):entity_state 是读路径事实源,facts 是治理
真源,双写 facade 桥接——漂移必须可见。已有实现只查 legacy→governed 方向;
本测试钉死三类漂移检出,并驱动补上 governed→legacy 反向:facts active 而
entity_state 无对应(例:event_projection / 写入时抽取产生的治理事实,读
路径看不见)= governed_only 面。
"""
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
    db = tmp_path / "shadow.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    monkeypatch.setenv("MASE_GOVERNANCE_DUAL_WRITE", "1")
    return db


def _dual_write(category, key, value, *, source_text=None):
    """真实双写路径:legacy 主写(mase2_upsert_fact)+ 治理副写(env 开关)。"""
    import re

    from mase_tools.memory.api import mase2_upsert_fact, mase2_write_interaction

    text = source_text or f"记录:{key} 为 {value}。"
    msg = mase2_write_interaction("t1", "user", text)
    log_id = int(re.search(r"ID (\d+)", msg).group(1))
    return mase2_upsert_fact(category, key, value, reason="user stated", source_log_id=log_id)


def _diff(**kw):
    from mase.governance.write_facade import GovernedFactWriteFacade

    return GovernedFactWriteFacade().shadow_read_diff(**kw)


class TestLegacyDriftDetection:
    def test_value_drift_is_detected(self, tmp_path, monkeypatch):
        db = _isolate(tmp_path, monkeypatch)
        _dual_write("project_status", "owner", "Alice", source_text="Owner is Alice.")
        # 人为制造漂移:直接改 entity_state(绕过 facade 的旁路写)
        conn = sqlite3.connect(db)
        conn.execute("UPDATE entity_state SET entity_value = 'Bob' WHERE entity_key = 'owner'")
        conn.commit()
        conn.close()

        report = _diff(category="project_status", key="owner")
        assert report["diff_count"] == 1
        assert report["diffs"][0]["explain"] == "legacy and governed values differ"
        assert report["diffs"][0]["legacy_value"] == "Bob"
        assert report["diffs"][0]["governed_value"] == "Alice"

    def test_missing_governed_row_is_detected(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        # 只写 legacy(不开治理双写路径):模拟历史 legacy-only 行
        from mase_tools.memory.api import mase2_upsert_fact

        # 关掉双写,产生纯 legacy 行
        import os
        os.environ.pop("MASE_GOVERNANCE_DUAL_WRITE", None)
        mase2_upsert_fact("project_status", "budget", "500")
        os.environ["MASE_GOVERNANCE_DUAL_WRITE"] = "1"

        report = _diff(category="project_status", key="budget")
        assert report["diff_count"] == 1
        assert report["diffs"][0]["governance_status"] == "missing"


class TestGovernedOnlyDirection:
    def test_governed_only_fact_is_reported(self, tmp_path, monkeypatch):
        """facts active 而 entity_state 无对应:读路径看不见的治理事实必须可见。"""
        _isolate(tmp_path, monkeypatch)
        from mase.governance.fact_contract import FactContract, new_fact_id
        from mase.governance.fact_store import propose_fact

        source = "会议记录:预算定为 8000 元。"
        fact = propose_fact(
            FactContract(
                fact_id=new_fact_id(), entity_id="user:t", claim_type="project_fact",
                subject="finance_budget", predicate="phoenix_budget", object_value="8000 元",
                confidence=0.9, observed_at="2026-07-12T00:00:00Z",
            ),
            "预算定为 8000 元",
            source_type="chat", source_id="m9", trust_level=3, source_full_text=source,
        )
        assert fact.status == "active"

        report = _diff(category="finance_budget")
        assert report["governed_only_count"] == 1
        row = report["governed_only"][0]
        assert row["category"] == "finance_budget"
        assert row["entity_key"] == "phoenix_budget"
        assert row["governed_value"] == "8000 元"

    def test_dual_written_fact_is_not_governed_only(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        _dual_write("project_status", "owner", "Alice", source_text="Owner is Alice.")
        report = _diff(category="project_status")
        assert report["governed_only_count"] == 0
        assert report["diff_count"] == 0

    def test_superseded_facts_do_not_count_as_governed_only(self, tmp_path, monkeypatch):
        """只有 active 才参与反向对照:superseded 链节点不是读路径缺失面。"""
        _isolate(tmp_path, monkeypatch)
        from mase.governance.fact_contract import FactContract, new_fact_id
        from mase.governance.fact_store import propose_fact

        for value in ("5000 元", "8000 元"):
            source = f"记录:预算 {value}。"
            propose_fact(
                FactContract(
                    fact_id=new_fact_id(), entity_id="user:t", claim_type="project_fact",
                    subject="finance_budget", predicate="phoenix_budget", object_value=value,
                    confidence=0.9, observed_at="2026-07-12T00:00:00Z",
                ),
                f"预算 {value}",
                source_type="chat", source_id="m9", trust_level=3, source_full_text=source,
            )
        report = _diff(category="finance_budget")
        assert report["governed_only_count"] == 1  # 只有 active 的 8000 一条
        assert report["governed_only"][0]["governed_value"] == "8000 元"
