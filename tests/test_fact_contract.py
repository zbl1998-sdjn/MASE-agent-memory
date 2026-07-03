"""FactContract v1 数据对象与治理四表 DDL 行为测试(P0 T1)。"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "governance.db"))


def _sample_contract(**overrides):
    from mase.governance.fact_contract import FactContract, new_fact_id

    kwargs = dict(
        fact_id=new_fact_id(),
        entity_id="media:abc123def456",
        claim_type="document_claim",
        subject="acme-po-2026",
        predicate="order_total",
        object_value="$12,340.00",
        confidence=0.9,
        observed_at="2026-07-04T00:00:00Z",
    )
    kwargs.update(overrides)
    return FactContract(**kwargs)


def test_fact_status_constants_cover_state_machine():
    from mase.governance.fact_contract import FactStatus

    assert FactStatus.CANDIDATE == "candidate"
    assert FactStatus.ACTIVE == "active"
    assert FactStatus.QUARANTINED == "quarantined"
    assert FactStatus.SUPERSEDED == "superseded"
    assert FactStatus.RETRACTED == "retracted"
    assert FactStatus.REJECTED == "rejected"
    assert FactStatus.EXPIRED == "expired"
    assert FactStatus.ALL == frozenset(
        {"candidate", "active", "quarantined", "superseded", "retracted", "rejected", "expired"}
    )


def test_trust_level_constants_match_governance_plan():
    # 总纲 §4.2.3:E5 用户显式陈述 … E0 可疑输入。
    from mase.governance.fact_contract import TrustLevel

    assert TrustLevel.E0 == 0
    assert TrustLevel.E1 == 1
    assert TrustLevel.E2 == 2
    assert TrustLevel.E3 == 3
    assert TrustLevel.E4 == 4
    assert TrustLevel.E5 == 5


def test_claim_type_constants_include_inference():
    from mase.governance.fact_contract import ClaimType

    assert ClaimType.DOCUMENT_CLAIM == "document_claim"
    assert ClaimType.INFERENCE == "inference"
    for name in ("preference", "profile", "project_fact", "tool_state"):
        assert name in ClaimType.ALL
    assert "document_claim" in ClaimType.ALL and "inference" in ClaimType.ALL


def test_new_ids_are_prefixed_and_unique():
    from mase.governance.fact_contract import new_evidence_id, new_fact_id

    fact_ids = {new_fact_id() for _ in range(50)}
    ev_ids = {new_evidence_id() for _ in range(50)}
    assert len(fact_ids) == 50 and len(ev_ids) == 50
    assert all(i.startswith("fact_") for i in fact_ids)
    assert all(i.startswith("ev_") for i in ev_ids)


def test_evidence_span_is_frozen():
    from mase.governance.fact_contract import EvidenceSpan, new_evidence_id

    span = EvidenceSpan(
        evidence_id=new_evidence_id(),
        source_type="media_extraction",
        source_id="42",
        span_start=10,
        span_end=25,
        quote_hash="deadbeef" * 8,
        quote_excerpt="Invoice total 4200",
        trust_level=4,
        created_at="2026-07-04T00:00:00Z",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        span.span_start = 0  # type: ignore[misc]


def test_fact_contract_is_frozen_with_v1_defaults():
    contract = _sample_contract()
    assert contract.schema_version == "fact_contract.v1"
    assert contract.status == "candidate"
    assert contract.visibility == "private"
    assert contract.sensitivity == "normal"
    assert contract.qualifiers is None
    assert contract.tenant_id == "" and contract.workspace_id == ""
    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.status = "active"  # type: ignore[misc]


def test_fact_contract_row_roundtrip_preserves_qualifiers():
    from mase.governance.fact_contract import FactContract

    contract = _sample_contract(
        qualifiers={"scope": "docs/po.pdf"},
        confidence_basis={"method": "mechanical_span_bind"},
        status="active",
        valid_from="2026-01-01",
        created_at="2026-07-04T00:00:00Z",
        updated_at="2026-07-04T00:00:00Z",
    )
    row = contract.to_row()
    # 行键与 facts 表列名一致(object 是列名,object_value 是属性名)。
    assert row["object"] == "$12,340.00"
    assert "object_value" not in row
    assert isinstance(row["qualifiers_json"], str)
    back = FactContract.from_row(row)
    assert back == contract


def test_fact_contract_row_roundtrip_none_qualifiers():
    from mase.governance.fact_contract import FactContract

    contract = _sample_contract()
    row = contract.to_row()
    assert row["qualifiers_json"] is None
    assert FactContract.from_row(row) == contract


def test_evidence_span_row_roundtrip_allows_null_span():
    from mase.governance.fact_contract import EvidenceSpan, new_evidence_id

    span = EvidenceSpan(
        evidence_id=new_evidence_id(),
        source_type="media_extraction",
        source_id="42",
        span_start=None,
        span_end=None,
        quote_hash="ab" * 32,
        quote_excerpt="未定位引文",
        trust_level=1,
        created_at="2026-07-04T00:00:00Z",
    )
    assert EvidenceSpan.from_row(span.to_row()) == span


def test_governance_tables_created_on_fresh_db(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from contextlib import closing

    from mase_tools.memory.db_core import get_connection

    with closing(get_connection()) as conn:
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }
    for table in ("facts", "evidence_spans", "fact_evidence", "fact_edges"):
        assert table in names, f"缺表 {table}"
    assert "idx_facts_entity" in names
    assert "idx_facts_subject_pred" in names
