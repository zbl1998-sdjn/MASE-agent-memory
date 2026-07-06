"""治理式巩固/遗忘 v1 gold set(设计规范 2026-07-07 §6,全确定性)。

不变式:成员行一字节不改;摘要走唯一写入口(门控生效、幂等);retract 摘要
即整体回退;遗忘=留痕撤回。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_ENTITY = "user:alice"
_VALUES = ["100 元", "200 元", "300 元", "400 元", "500 元"]


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "facts.db"))


def _seed_chain(values=_VALUES, predicate="budget"):
    """依次提交同键不同值:前 n-1 条自动 superseded,末条 active。"""
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    fact_ids = []
    for i, value in enumerate(values):
        source = f"会议纪要第{i}页:预算调整为 {value},自即日起生效。"
        contract = FactContract(
            fact_id=new_fact_id(),
            entity_id=_ENTITY,
            claim_type="project_fact",
            subject="alice",
            predicate=predicate,
            object_value=value,
            confidence=0.9,
            observed_at=f"2026-06-0{i + 1}T00:00:00Z",
        )
        final = propose_fact(
            contract, value,
            source_type="chat", source_id=f"msg-{i}", trust_level=3,
            source_full_text=source,
        )
        assert final.status == "active"
        fact_ids.append(final.fact_id)
    return fact_ids


def _rows_snapshot(fact_ids):
    from contextlib import closing

    from mase_tools.memory.db_core import get_connection

    with closing(get_connection(None)) as conn:
        rows = conn.execute(
            f"SELECT * FROM facts WHERE fact_id IN ({','.join('?' * len(fact_ids))}) ORDER BY fact_id",
            fact_ids,
        ).fetchall()
    return [tuple(row) for row in rows]


def test_candidates_only_count_closed_chains(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.consolidation import find_consolidation_candidates

    _seed_chain()
    candidates = find_consolidation_candidates(_ENTITY, min_chain=4)
    assert candidates == [{"subject": "alice", "predicate": "budget", "chain_length": 4}]
    assert find_consolidation_candidates(_ENTITY, min_chain=5) == []


def test_consolidate_chain_creates_e2_summary_and_leaves_members_untouched(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.consolidation import consolidate_chain
    from mase.governance.fact_store import get_fact, list_facts

    ids = _seed_chain()
    member_ids = ids[:-1]  # 前四条已 superseded
    before = _rows_snapshot(member_ids)

    outcome = consolidate_chain(_ENTITY, "alice", "budget", min_chain=4)
    assert outcome["status"] == "active"
    assert outcome["member_ids"] == member_ids

    # 成员行一字节不改。
    assert _rows_snapshot(member_ids) == before

    summary = get_fact(outcome["summary_fact_id"])
    assert summary is not None
    assert summary["claim_type"] == "derived_summary"
    trajectory = json.loads(summary["object"])
    assert [t["value"] for t in trajectory] == _VALUES[:-1]  # 按 observed_at 时序
    qualifiers = json.loads(summary["qualifiers_json"])
    assert qualifiers["scope"] == "consolidation"
    assert qualifiers["consolidation"]["member_count"] == 4
    # 证据:1 条自定位 supports span(E2)+ 逐成员 derived_from 联结。
    roles = sorted(e["role"] for e in summary["evidence"])
    assert roles.count("derived_from") == 4 and roles.count("supports") == 1
    supports = [e for e in summary["evidence"] if e["role"] == "supports"][0]
    assert supports["trust_level"] == 2 and supports["span_start"] is not None

    # 现行 active 值不被摘要顶掉(scope 隔离)。
    actives = [f for f in list_facts(status="active") if f["predicate"] == "budget"]
    assert {f["fact_id"] for f in actives} == {ids[-1], outcome["summary_fact_id"]}


def test_consolidate_is_idempotent(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from contextlib import closing

    from mase.governance.consolidation import consolidate_chain
    from mase_tools.memory.db_core import get_connection

    _seed_chain()
    first = consolidate_chain(_ENTITY, "alice", "budget")
    second = consolidate_chain(_ENTITY, "alice", "budget")
    assert second["summary_fact_id"] == first["summary_fact_id"]
    with closing(get_connection(None)) as conn:
        n_summaries = conn.execute(
            "SELECT COUNT(*) AS n FROM facts WHERE claim_type = 'derived_summary'"
        ).fetchone()["n"]
        n_actions = conn.execute(
            "SELECT COUNT(*) AS n FROM review_actions WHERE action = 'consolidate'"
        ).fetchone()["n"]
    assert n_summaries == 1 and n_actions == 1


def test_short_chain_is_skipped_without_writes(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.consolidation import consolidate_chain
    from mase.governance.fact_store import list_facts

    _seed_chain(values=["100 元", "200 元"])  # 链长 1,不达标
    outcome = consolidate_chain(_ENTITY, "alice", "budget", min_chain=4)
    assert outcome["status"] == "skipped"
    assert all(f["claim_type"] != "derived_summary" for f in list_facts())


def test_retract_summary_restores_pre_consolidation_view(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.consolidation import consolidate_chain
    from mase.governance.fact_store import get_fact, retract_fact

    ids = _seed_chain()
    outcome = consolidate_chain(_ENTITY, "alice", "budget")
    assert retract_fact(outcome["summary_fact_id"], "undo consolidation", reviewer="tester")
    summary = get_fact(outcome["summary_fact_id"])
    assert summary is not None and summary["status"] == "retracted"
    # 成员与现行值全程未动。
    for fact_id in ids[:-1]:
        member = get_fact(fact_id, with_evidence=False)
        assert member is not None and member["status"] == "superseded"
    head = get_fact(ids[-1], with_evidence=False)
    assert head is not None and head["status"] == "active"


def test_forget_fact_retracts_with_forget_audit_trail(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from contextlib import closing

    from mase.governance.consolidation import forget_fact
    from mase.governance.fact_store import get_fact
    from mase_tools.memory.db_core import get_connection

    ids = _seed_chain(values=["100 元", "200 元"])
    assert forget_fact(ids[-1], "用户要求删除预算记忆", reviewer="alice")
    fact = get_fact(ids[-1])
    assert fact is not None and fact["status"] == "retracted"
    assert fact["evidence"], "遗忘只撤回资格,证据行必须保留"
    with closing(get_connection(None)) as conn:
        row = conn.execute(
            "SELECT reviewer, reason FROM review_actions WHERE action = 'forget' AND fact_id = ?",
            (ids[-1],),
        ).fetchone()
    assert row is not None and row["reviewer"] == "alice" and "预算" in row["reason"]
    assert forget_fact("fact_missing", "no such") is False


def test_pii_values_never_form_consolidatable_chains(tmp_path, monkeypatch):
    """PII 在准入层(G3)即被隔离,supersession 链根本形成不了——
    分层防御:巩固层的输入面天然无 PII,派生摘要不可能携带隔离值。"""
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.consolidation import find_consolidation_candidates
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    for i, value in enumerate(["13800138000", "13900139000", "13700137000", "13600136000"]):
        source = f"客服记录第{i}页:联系电话 {value}"
        final = propose_fact(
            FactContract(
                fact_id=new_fact_id(),
                entity_id=_ENTITY,
                claim_type="profile",
                subject="alice",
                predicate="contact_phone",
                object_value=value,
                confidence=0.9,
                observed_at=f"2026-06-0{i + 1}T00:00:00Z",
            ),
            value,
            source_type="chat", source_id=f"msg-{i}", trust_level=3,
            source_full_text=source,
        )
        assert final.status == "quarantined"  # G3:手机号隔离,不进 active
    assert find_consolidation_candidates(_ENTITY, min_chain=1) == []
