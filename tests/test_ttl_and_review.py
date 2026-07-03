"""TTL 过期执行与人工 review 通道测试(P1 T4)。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOURCE_TEXT = "构建目录 /tmp/build-42。用户说预算其实是 800 元。预算 500 元。联系人电话 13912345678"


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "ttl.db"))


def _propose(predicate, value, evidence, *, trust=4, claim_type="project_fact", valid_to=None,
             observed_at="2026-07-04T00:00:00Z"):
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    return propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="user:default",
            claim_type=claim_type,
            subject="project_facts",
            predicate=predicate,
            object_value=value,
            confidence=0.9,
            observed_at=observed_at,
            valid_to=valid_to,
        ),
        evidence,
        source_type="memory_log",
        source_id="1",
        trust_level=trust,
        source_full_text=SOURCE_TEXT,
    )


# ---------- TTL ----------

def test_expire_due_facts_migrates_only_due(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    due = _propose("build_dir", "/tmp/build-42", "构建目录 /tmp/build-42",
                   valid_to="2026-07-02T00:00:00Z")
    fresh = _propose("budget", "800 元", "用户说预算其实是 800 元",
                     valid_to="2026-12-31T00:00:00Z")
    assert due.status == "active" and fresh.status == "active"

    from mase.governance.fact_store import expire_due_facts, get_fact

    moved = expire_due_facts(now="2026-07-04T00:00:00Z")
    assert moved == 1
    assert get_fact(due.fact_id)["status"] == "expired"
    assert get_fact(fresh.fact_id)["status"] == "active"


def test_list_facts_lazily_expires(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    due = _propose("build_dir", "/tmp/build-42", "构建目录 /tmp/build-42",
                   valid_to="2020-01-01T00:00:00Z")  # 已过期
    from mase.governance.fact_store import list_facts

    active = list_facts(status="active")
    assert due.fact_id not in {f["fact_id"] for f in active}

    conn = sqlite3.connect(tmp_path / "ttl.db")
    status = conn.execute(
        "SELECT status FROM facts WHERE fact_id=?", (due.fact_id,)
    ).fetchone()[0]
    conn.close()
    assert status == "expired"  # 惰性写回


def test_get_fact_lazily_expires(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    due = _propose("build_dir", "/tmp/build-42", "构建目录 /tmp/build-42",
                   valid_to="2020-01-01T00:00:00Z")
    from mase.governance.fact_store import get_fact

    assert get_fact(due.fact_id)["status"] == "expired"


# ---------- review 通道 ----------

def _quarantined_with_span(tmp_path, monkeypatch):
    """PII 值 → quarantined 但证据已定位(可 approve)。"""
    return _propose("contact_phone", "13912345678", "联系人电话 13912345678", trust=5)


def test_approve_located_quarantined_becomes_active(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    fact = _quarantined_with_span(tmp_path, monkeypatch)
    assert fact.status == "quarantined"

    from mase.governance.fact_store import approve_fact, get_fact, list_facts

    ok, message = approve_fact(fact.fact_id, reviewer="zbl", reason="用户确认可记")
    assert ok, message
    assert get_fact(fact.fact_id)["status"] == "active"
    # 不变式:approve 出来的 active 也必须有已定位证据
    for f in list_facts(status="active"):
        detail = get_fact(f["fact_id"])
        assert any(s["span_start"] is not None for s in detail["evidence"])

    conn = sqlite3.connect(tmp_path / "ttl.db")
    conn.row_factory = sqlite3.Row
    action = conn.execute("SELECT * FROM review_actions ORDER BY created_at DESC").fetchone()
    conn.close()
    assert action["action"] == "approve" and action["reviewer"] == "zbl"


def test_approve_without_located_span_is_refused(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    fact = _propose("budget", "999 元", "原文里没有这句", trust=5)  # 定位失败 → quarantined
    from mase.governance.fact_store import approve_fact, get_fact

    ok, message = approve_fact(fact.fact_id, reviewer="zbl")
    assert not ok and "证据" in message
    assert get_fact(fact.fact_id)["status"] == "quarantined"


def test_approve_non_quarantined_is_refused(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    fact = _propose("budget", "800 元", "用户说预算其实是 800 元", trust=5)
    from mase.governance.fact_store import approve_fact

    ok, message = approve_fact(fact.fact_id, reviewer="zbl")
    assert not ok and "quarantined" in message
    ok, message = approve_fact("fact_missing", reviewer="zbl")
    assert not ok


def test_approve_conflict_fact_supersedes_opponent(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    old = _propose("budget", "800 元", "用户说预算其实是 800 元", trust=5)
    new = _propose("budget", "500 元", "预算 500 元", trust=1)  # 低 trust → 冲突隔离
    assert new.status == "quarantined"

    from mase.governance.fact_store import approve_fact, get_fact, supersession_chain

    ok, _ = approve_fact(new.fact_id, reviewer="zbl", reason="人工核实新值正确")
    assert ok
    assert get_fact(new.fact_id)["status"] == "active"
    assert get_fact(old.fact_id)["status"] == "superseded"  # 人工裁决后对手退位
    chain = supersession_chain(old.fact_id)
    assert [f["fact_id"] for f in chain] == [new.fact_id, old.fact_id]


def test_reject_quarantined_fact(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    fact = _quarantined_with_span(tmp_path, monkeypatch)
    from mase.governance.fact_store import get_fact, reject_fact

    ok, _ = reject_fact(fact.fact_id, reviewer="zbl", reason="不需要记")
    assert ok
    assert get_fact(fact.fact_id)["status"] == "rejected"

    ok, _ = reject_fact(fact.fact_id, reviewer="zbl")  # 已 rejected,不可重复
    assert not ok


def test_review_queue_lists_quarantined_with_conflict_context(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    old = _propose("budget", "800 元", "用户说预算其实是 800 元", trust=5)
    conflicted = _propose("budget", "500 元", "预算 500 元", trust=1)
    pii = _quarantined_with_span(tmp_path, monkeypatch)

    from mase.governance.fact_store import list_review_queue

    queue = list_review_queue()
    by_id = {item["fact_id"]: item for item in queue}
    assert set(by_id) == {conflicted.fact_id, pii.fact_id}
    assert by_id[conflicted.fact_id]["conflicts"][0]["fact_id"] == old.fact_id
    assert by_id[pii.fact_id]["conflicts"] == []
    assert by_id[pii.fact_id]["evidence"]  # 证据一并带出
