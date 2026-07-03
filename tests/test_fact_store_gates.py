"""fact_store 门控集成测试(P1 T2):G2/G3/G5 编排、脱敏落库、gate 留痕。

占位凭据以运行时拼接构造,避免密钥扫描器字面命中;绝无真实凭据。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FAKE_SECRET = "api_key=" + "dummy-not-real-99"  # allowlist-secret
SOURCE_WITH_SECRET = f"运维手册\n{FAKE_SECRET}\n完"
SOURCE_TEXT = "采购单 PO-2026\n联系人电话 13912345678\n总额 $12,340.00"


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "gates.db"))


def _contract(**overrides):
    from mase.governance.fact_contract import FactContract, new_fact_id

    kwargs = dict(
        fact_id=new_fact_id(),
        entity_id="media:abc",
        claim_type="document_claim",
        subject="general_facts",
        predicate="order_total",
        object_value="$12,340.00",
        confidence=0.9,
        observed_at="2026-07-04T00:00:00Z",
    )
    kwargs.update(overrides)
    return FactContract(**kwargs)


def _propose(contract, evidence, source=SOURCE_TEXT):
    from mase.governance.fact_store import propose_fact

    return propose_fact(
        contract,
        evidence,
        source_type="media_extraction",
        source_id="17",
        trust_level=4,
        source_full_text=source,
    )


def _all_text_in_db(db):
    conn = sqlite3.connect(db)
    chunks = []
    for table in ("facts", "evidence_spans", "fact_evidence", "review_actions"):
        for row in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608 — 表名白名单
            chunks.append(repr(row))
    conn.close()
    return "\n".join(chunks)


def test_secret_value_is_rejected_and_redacted(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(
        _contract(predicate="ops_credential", object_value=FAKE_SECRET),
        FAKE_SECRET,
        source=SOURCE_WITH_SECRET,
    )
    assert result.status == "rejected"
    assert result.object_value.startswith("[REDACTED:")
    assert result.sensitivity == "secret"

    db = tmp_path / "gates.db"
    stored = _all_text_in_db(db)
    assert "dummy-not-real-99" not in stored  # 原值不落任何列
    assert "[REDACTED:" in stored

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    action = conn.execute("SELECT * FROM review_actions").fetchone()
    conn.close()
    assert action["action"] == "security_redact"
    assert action["reviewer"] == "system:gate"
    assert action["fact_id"] == result.fact_id


def test_secret_in_evidence_only_is_also_rejected(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(
        _contract(object_value="见运维手册"),
        FAKE_SECRET,
        source=SOURCE_WITH_SECRET,
    )
    assert result.status == "rejected"
    assert "dummy-not-real-99" not in _all_text_in_db(tmp_path / "gates.db")


def test_pii_value_is_quarantined_personal(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(
        _contract(predicate="contact_phone", object_value="13912345678"),
        "联系人电话 13912345678",
    )
    assert result.status == "quarantined"
    assert result.sensitivity == "personal"
    # PII 证据留痕(等 review),span 应已定位
    from mase.governance.fact_store import get_fact

    (span,) = get_fact(result.fact_id)["evidence"]
    assert span["span_start"] is not None


def test_blank_predicate_quarantined_with_gate_note(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(_contract(predicate="  "), "总额 $12,340.00")
    assert result.status == "quarantined"
    from mase.governance.fact_store import get_fact

    detail = get_fact(result.fact_id)
    gate = json.loads(detail["confidence_basis_json"])["gate"]
    assert gate["gate"] == "G2"
    assert "predicate" in gate["reason"]


def test_tool_state_gets_ttl_in_db(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(
        _contract(claim_type="tool_state", predicate="build_dir", object_value="PO-2026"),
        "采购单 PO-2026",
    )
    assert result.status == "active"
    assert result.valid_to == "2026-07-11T00:00:00Z"
    from mase.governance.fact_store import get_fact

    assert get_fact(result.fact_id)["valid_to"] == "2026-07-11T00:00:00Z"


def test_clean_fact_still_active_with_no_gate_note(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    result = _propose(_contract(), "总额 $12,340.00")
    assert result.status == "active"
    from mase.governance.fact_store import get_fact

    basis = json.loads(get_fact(result.fact_id)["confidence_basis_json"] or "{}")
    assert "gate" not in basis
