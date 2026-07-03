"""G4 冲突治理测试(P1 T3):trust 阶梯、conflicts_with 显性边、valid_time 闭合。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOURCE_TEXT = "会议纪要:预算 500 元。修订:预算 1000 元。用户说预算其实是 800 元。"


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "conflict.db"))


def _propose(value, evidence, trust, observed_at="2026-07-04T00:00:00Z"):
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    return propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="user:default",
            claim_type="project_fact",
            subject="project_facts",
            predicate="budget",
            object_value=value,
            confidence=0.9,
            observed_at=observed_at,
        ),
        evidence,
        source_type="memory_log",
        source_id="1",
        trust_level=trust,
        source_full_text=SOURCE_TEXT,
    )


def test_resolve_conflict_trust_ladder():
    from mase.governance.conflict import QUARANTINE_NEW, SUPERSEDE, resolve_conflict

    assert resolve_conflict(5, 4) == SUPERSEDE
    assert resolve_conflict(4, 4) == SUPERSEDE  # 同 trust = 时间性更新
    assert resolve_conflict(1, 5) == QUARANTINE_NEW


def test_lower_trust_new_value_does_not_silently_override(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    old = _propose("800 元", "用户说预算其实是 800 元", trust=5)
    new = _propose("500 元", "预算 500 元", trust=1)

    from mase.governance.fact_store import get_fact, list_facts

    assert get_fact(old.fact_id)["status"] == "active"  # 高 trust 旧事实不动
    assert new.status == "quarantined"
    active = list_facts(status="active")
    assert [f["fact_id"] for f in active] == [old.fact_id]

    conn = sqlite3.connect(tmp_path / "conflict.db")
    conn.row_factory = sqlite3.Row
    edge = conn.execute("SELECT * FROM fact_edges WHERE edge_type='conflicts_with'").fetchone()
    conn.close()
    assert edge["from_fact_id"] == new.fact_id and edge["to_fact_id"] == old.fact_id

    gate = json.loads(get_fact(new.fact_id)["confidence_basis_json"])["gate"]
    assert gate["gate"] == "G4"


def test_higher_trust_supersedes_and_closes_valid_time(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    old = _propose("500 元", "预算 500 元", trust=4, observed_at="2026-07-01T00:00:00Z")
    new = _propose("800 元", "用户说预算其实是 800 元", trust=5, observed_at="2026-07-04T00:00:00Z")
    assert new.status == "active"

    from mase.governance.fact_store import get_fact, supersession_chain

    old_detail = get_fact(old.fact_id)
    assert old_detail["status"] == "superseded"
    assert old_detail["valid_to"] == "2026-07-04T00:00:00Z"  # 时效闭合到新事实 observed_at
    chain = supersession_chain(old.fact_id)
    assert [f["fact_id"] for f in chain] == [new.fact_id, old.fact_id]


def test_same_trust_preference_change_supersedes(tmp_path, monkeypatch):
    # §8.2 验收原文:偏好变更样本能正确 supersede 旧事实。
    _isolate_db(tmp_path, monkeypatch)
    old = _propose("500 元", "预算 500 元", trust=5)
    new = _propose("1000 元", "修订:预算 1000 元", trust=5)
    assert new.status == "active"

    from mase.governance.fact_store import get_fact, list_facts

    assert get_fact(old.fact_id)["status"] == "superseded"
    assert [f["fact_id"] for f in list_facts(status="active")] == [new.fact_id]


def test_same_value_reobservation_is_not_a_conflict(tmp_path, monkeypatch):
    # 值相同不走 G4:低 trust 复述同值不会制造 conflicts_with 边。
    _isolate_db(tmp_path, monkeypatch)
    _propose("800 元", "用户说预算其实是 800 元", trust=5)
    second = _propose("800 元", "预算 500 元", trust=1)  # 同值,不同证据/低 trust
    assert second.status in ("active", "quarantined")  # 不产生冲突边即可

    conn = sqlite3.connect(tmp_path / "conflict.db")
    edges = conn.execute("SELECT COUNT(*) FROM fact_edges WHERE edge_type='conflicts_with'").fetchone()[0]
    conn.close()
    assert edges == 0
