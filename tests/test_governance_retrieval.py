"""白盒召回测试(P2 T1):归一化变体命中、可解释打分、确定性排序。"""
from __future__ import annotations

import sys
from contextlib import closing
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOURCE_TEXT = (
    "会议纪要:预算 800 元,采购单 P O - 2026,总额 $12,340.00。"
    "旧预算 500 元。构建目录 /tmp/build-42。低信源说预算 300 元。"
)


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "retrieval.db"))


def _propose(predicate, value, evidence, *, trust=5, entity="user:default",
             claim_type="project_fact", valid_to=None, observed_at="2026-07-04T00:00:00Z"):
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    return propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id=entity,
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


def _seed(tmp_path, monkeypatch):
    """active(经一次变更)+ 冲突对 + 千分位/空白值 + 过期 tool_state。"""
    _isolate_db(tmp_path, monkeypatch)
    _propose("budget", "500 元", "旧预算 500 元", observed_at="2026-07-01T00:00:00Z")  # → superseded
    active = _propose("budget", "800 元", "预算 800 元")
    conflicted = _propose("budget", "300 元", "低信源说预算 300 元", trust=1)  # → quarantined + 冲突边
    total = _propose("order_total", "$12,340.00", "总额 $12,340.00", entity="media:doc1")
    po = _propose("po_number", "P O - 2026", "采购单 P O - 2026", entity="media:doc1")
    expired = _propose("build_dir", "/tmp/build-42", "构建目录 /tmp/build-42",
                       claim_type="tool_state", valid_to="2020-01-01T00:00:00Z")
    return active, conflicted, total, po, expired


def test_audit_tables_created(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.db_core import get_connection

    with closing(get_connection()) as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "retrieval_runs" in names and "context_packs" in names


def test_keyword_hits_object_value(tmp_path, monkeypatch):
    active, *_ = _seed(tmp_path, monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    plan, candidates = retrieve_facts(["800"])
    ids = [c.fact.fact_id for c in candidates]
    assert active.fact_id in ids
    top = candidates[0]
    assert top.fact.fact_id == active.fact_id
    assert any("800" in why for why in top.why_selected)
    assert plan.trace_id.startswith("tr_")
    assert plan.classifier == "none.v1"


def test_thousand_separator_and_currency_variant(tmp_path, monkeypatch):
    _, _, total, _, _ = _seed(tmp_path, monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    _, candidates = retrieve_facts(["12340"])
    assert candidates and candidates[0].fact.fact_id == total.fact_id


def test_whitespace_variant(tmp_path, monkeypatch):
    _, _, _, po, _ = _seed(tmp_path, monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    _, candidates = retrieve_facts(["PO-2026"])
    assert candidates and candidates[0].fact.fact_id == po.fact_id


def test_hyphen_underscore_folding(tmp_path, monkeypatch):
    # 真实盲区回归钉(P2 验收发现):key 规范化把 - 转 _,
    # 连字符形关键词必须命中下划线形 predicate。
    _isolate_db(tmp_path, monkeypatch)
    fact = _propose("invoice_total_acme_inv_2026_001", "4200 EUR", "预算 800 元")
    from mase.governance.retrieval import retrieve_facts

    _, candidates = retrieve_facts(["ACME-INV-2026-001"])
    assert candidates and candidates[0].fact.fact_id == fact.fact_id


def test_entity_filter(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    plan, candidates = retrieve_facts(["预算", "12340"], entity_id="media:doc1")
    assert candidates
    assert all(c.fact.entity_id == "media:doc1" for c in candidates)
    assert plan.filters.get("entity_id") == "media:doc1"


def test_breakdown_sums_to_score_with_spec_weights(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    from mase.governance.retrieval import WEIGHTS, retrieve_facts

    _, candidates = retrieve_facts(["800"])
    top = candidates[0]
    expected = sum(WEIGHTS[k] * v for k, v in top.breakdown.items() if not k.endswith("_penalty"))
    expected -= sum(WEIGHTS[k] * v for k, v in top.breakdown.items() if k.endswith("_penalty"))
    assert abs(top.score - expected) < 1e-9
    # §4.5.3 权重原值抽查
    assert WEIGHTS["exact_entity_match"] == 0.30
    assert WEIGHTS["conflict_penalty"] == 0.30
    assert WEIGHTS["tag_match"] == 0.05
    assert top.breakdown["tag_match"] == 0.0  # v1 如实恒 0


def test_status_penalties(tmp_path, monkeypatch):
    active, conflicted, _, _, expired = _seed(tmp_path, monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    _, candidates = retrieve_facts(["800", "300", "500", "build-42"])
    by_id = {c.fact.fact_id: c for c in candidates}
    # active 事实有冲突对手 → conflict_penalty
    assert by_id[active.fact_id].breakdown["conflict_penalty"] == 1.0
    # 隔离的冲突方也在候选中(供 C3),同样带冲突罚
    assert by_id[conflicted.fact_id].breakdown["conflict_penalty"] == 1.0
    # 过期 tool_state → staleness
    assert by_id[expired.fact_id].breakdown["staleness_penalty"] == 1.0
    assert by_id[expired.fact_id].breakdown["recency_or_validity"] == 0.0


def test_superseded_candidate_has_staleness(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    _, candidates = retrieve_facts(["500"])
    superseded = [c for c in candidates if c.fact.status == "superseded"]
    assert superseded and superseded[0].breakdown["staleness_penalty"] == 1.0


def test_rejected_never_candidate(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    fake = "api_key=" + "dummy-p2-rejected"  # allowlist-secret
    rejected = _propose("cred", fake, fake)
    assert rejected.status == "rejected"
    from mase.governance.retrieval import retrieve_facts

    _, candidates = retrieve_facts(["REDACTED", "cred"])
    assert all(c.fact.status != "rejected" for c in candidates)


def test_deterministic_tie_break_by_fact_id(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    a = _propose("alpha", "同分值A", "预算 800 元", entity="media:x")
    b = _propose("beta", "同分值B", "旧预算 500 元", entity="media:x")
    from mase.governance.retrieval import retrieve_facts

    _, candidates = retrieve_facts(["同分值"])
    assert len(candidates) == 2
    assert candidates[0].score == candidates[1].score
    assert [c.fact.fact_id for c in candidates] == sorted([a.fact_id, b.fact_id])
