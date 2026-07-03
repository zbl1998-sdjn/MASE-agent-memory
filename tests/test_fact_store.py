"""fact_store 状态机与唯一写入口行为测试(P0 T3)。

核心不变式:任何 API 路径都无法产生"active 且无 evidence(或 span 为 NULL)"的事实。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOURCE_TEXT = "采购单 PO-2026\n供应商 宏远贸易\n总额 $12,340.00\n交货日期 12/28/2026"


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "facts.db"))


def _contract(**overrides):
    from mase.governance.fact_contract import FactContract, new_fact_id

    kwargs = dict(
        fact_id=new_fact_id(),
        entity_id="media:abc123def456",
        claim_type="document_claim",
        subject="po-2026",
        predicate="order_total",
        object_value="$12,340.00",
        confidence=0.9,
        observed_at="2026-07-04T00:00:00Z",
        qualifiers={"scope": "docs/po.pdf"},
    )
    kwargs.update(overrides)
    return FactContract(**kwargs)


def _propose(contract, evidence_text, **overrides):
    from mase.governance.fact_store import propose_fact

    kwargs = dict(
        source_type="media_extraction",
        source_id="17",
        trust_level=4,
        source_full_text=SOURCE_TEXT,
    )
    kwargs.update(overrides)
    return propose_fact(contract, evidence_text, **kwargs)


def _assert_active_invariant():
    """所有 active 事实都必须有至少一条 span 非 NULL 的证据。"""
    from mase.governance.fact_store import get_fact, list_facts

    for fact in list_facts(status="active"):
        detail = get_fact(fact["fact_id"])
        assert detail is not None
        spans = detail["evidence"]
        assert spans, f"active 事实 {fact['fact_id']} 无证据"
        assert any(
            s["span_start"] is not None and s["span_end"] is not None for s in spans
        ), f"active 事实 {fact['fact_id']} 证据全部无 span"


def test_located_evidence_becomes_active_with_span(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(_contract(), "总额 $12,340.00")
    assert result.status == "active"
    assert result.created_at and result.updated_at

    from mase.governance.fact_store import get_fact

    detail = get_fact(result.fact_id)
    assert detail is not None
    assert detail["status"] == "active"
    (span,) = detail["evidence"]
    matched = SOURCE_TEXT[span["span_start"] : span["span_end"]]
    assert matched == "总额 $12,340.00"
    assert span["quote_hash"] == hashlib.sha256(matched.encode("utf-8")).hexdigest()
    assert span["trust_level"] == 4
    _assert_active_invariant()


def test_fabricated_evidence_is_quarantined_with_null_span(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(_contract(), "总额 $99,999.99")  # 原文中不存在
    assert result.status == "quarantined"

    from mase.governance.fact_store import get_fact

    detail = get_fact(result.fact_id)
    assert detail is not None
    (span,) = detail["evidence"]  # 证据仍留痕供 review
    assert span["span_start"] is None and span["span_end"] is None
    assert span["quote_excerpt"] == "总额 $99,999.99"
    _assert_active_invariant()


def test_inference_claim_is_quarantined_even_if_located(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(_contract(claim_type="inference"), "总额 $12,340.00")
    assert result.status == "quarantined"
    _assert_active_invariant()


def test_preset_active_status_cannot_smuggle_past_binder(tmp_path, monkeypatch):
    # 调用方伪造 status=active + 假证据,店内状态机必须压回 quarantined。
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(_contract(status="active"), "编造的引文")
    assert result.status == "quarantined"
    _assert_active_invariant()


def test_same_key_new_fact_supersedes_old_active(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    first = _propose(_contract(), "总额 $12,340.00")
    second = _propose(
        _contract(object_value="12/28/2026"), "交货日期 12/28/2026"
    )
    assert second.status == "active"

    from mase.governance.fact_store import get_fact, list_facts, supersession_chain

    assert get_fact(first.fact_id)["status"] == "superseded"
    active = list_facts(status="active")
    assert [f["fact_id"] for f in active] == [second.fact_id]

    chain = supersession_chain(first.fact_id)
    assert [f["fact_id"] for f in chain] == [second.fact_id, first.fact_id]
    assert supersession_chain(second.fact_id) == chain  # 链上任一点回放一致
    _assert_active_invariant()


def test_different_scope_does_not_supersede(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    first = _propose(_contract(qualifiers={"scope": "docs/po.pdf"}), "总额 $12,340.00")
    second = _propose(
        _contract(qualifiers={"scope": "docs/other.pdf"}, object_value="PO-2026"),
        "采购单 PO-2026",
    )
    from mase.governance.fact_store import list_facts

    active_ids = {f["fact_id"] for f in list_facts(status="active")}
    assert active_ids == {first.fact_id, second.fact_id}
    _assert_active_invariant()


def test_idempotent_propose_returns_existing_fact(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    first = _propose(_contract(), "总额 $12,340.00")
    second = _propose(_contract(), "总额 $12,340.00")  # 同键同值同证据
    assert second.fact_id == first.fact_id

    from mase.governance.fact_store import list_facts

    assert len(list_facts()) == 1
    _assert_active_invariant()


def test_retract_active_fact(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    fact = _propose(_contract(), "总额 $12,340.00")

    from mase.governance.fact_store import get_fact, list_facts, retract_fact

    assert retract_fact(fact.fact_id, "人工复核:金额录入有误") is True
    assert list_facts(status="active") == []
    detail = get_fact(fact.fact_id)
    assert detail["status"] == "retracted"
    assert "人工复核" in (detail["confidence_basis_json"] or "")  # 撤回理由留痕

    assert retract_fact("fact_missing", "no such") is False


def test_list_facts_filters_by_entity_and_status(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    _propose(_contract(entity_id="media:aaa"), "总额 $12,340.00")
    _propose(
        _contract(entity_id="media:bbb", subject="other", object_value="宏远贸易"),
        "供应商 宏远贸易",
    )
    from mase.governance.fact_store import list_facts

    assert len(list_facts()) == 2
    assert len(list_facts(entity_id="media:aaa")) == 1
    assert len(list_facts(entity_id="media:bbb", status="active")) == 1
    assert list_facts(entity_id="media:aaa", status="quarantined") == []


def test_get_fact_without_evidence_flag(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    fact = _propose(_contract(), "总额 $12,340.00")

    from mase.governance.fact_store import get_fact

    detail = get_fact(fact.fact_id, with_evidence=False)
    assert detail is not None and "evidence" not in detail
    assert get_fact("fact_missing") is None
