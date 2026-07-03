"""admission_gate 纯函数行为测试(P1 T1):G2 结构 / G3 敏感 / G5 TTL。

测试凭据全部为占位样式(dummy/fake),并用运行时拼接避免密钥扫描器字面命中。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _contract(**overrides):
    from mase.governance.fact_contract import FactContract, new_fact_id

    kwargs = dict(
        fact_id=new_fact_id(),
        entity_id="media:abc",
        claim_type="document_claim",
        subject="general_facts",
        predicate="order_total",
        object_value="$100",
        confidence=0.9,
        observed_at="2026-07-04T00:00:00Z",
    )
    kwargs.update(overrides)
    return FactContract(**kwargs)


# ---------- G2 可结构化 ----------

def test_g2_passes_well_formed_contract():
    from mase.governance.admission_gate import check_structurable

    decision = check_structurable(_contract())
    assert decision.action == "pass" and decision.gate == "G2"


def test_g2_quarantines_blank_fields():
    from mase.governance.admission_gate import check_structurable

    for field, value in (("subject", "  "), ("predicate", ""), ("object_value", "\n")):
        decision = check_structurable(_contract(**{field: value}))
        assert decision.action == "quarantine", field
        assert field.replace("_value", "") in decision.reason or field in decision.reason


# ---------- G3 敏感检测 ----------

def test_g3_clean_text_passes():
    from mase.governance.admission_gate import scan_sensitive

    decision = scan_sensitive("供应商 宏远贸易", "总额 4200 元")
    assert decision.action == "pass" and decision.gate == "G3"


def test_g3_secret_keyword_assignment_rejects():
    from mase.governance.admission_gate import scan_sensitive

    decision = scan_sensitive("api_key=dummy-not-real-1234")  # allowlist-secret
    assert decision.action == "reject"
    assert decision.pattern is not None and "keyword" in decision.pattern


def test_g3_aws_style_key_rejects():
    from mase.governance.admission_gate import scan_sensitive

    fake_aws = "AKIA" + "DUMMYFAKE" + "0" * 7  # 占位样式,运行时拼接避免扫描器
    decision = scan_sensitive(f"凭据 {fake_aws} 已生成")
    assert decision.action == "reject"
    assert decision.pattern == "aws_access_key"


def test_g3_pem_private_key_rejects():
    from mase.governance.admission_gate import scan_sensitive

    pem_header = "-----BEGIN " + "PRIVATE KEY-----"  # 运行时拼接避免 detect-private-key
    decision = scan_sensitive(pem_header)
    assert decision.action == "reject"
    assert decision.pattern == "pem_private_key"


def test_g3_pii_mobile_quarantines():
    from mase.governance.admission_gate import scan_sensitive

    decision = scan_sensitive("联系人电话 13912345678")
    assert decision.action == "quarantine"
    assert decision.pattern == "cn_mobile"


def test_g3_pii_id_card_and_email_quarantine():
    from mase.governance.admission_gate import scan_sensitive

    assert scan_sensitive("身份证 11010119900101003X").action == "quarantine"
    assert scan_sensitive("邮箱 someone@example.com").action == "quarantine"


def test_g3_secret_takes_precedence_over_pii():
    from mase.governance.admission_gate import scan_sensitive

    decision = scan_sensitive("password=dummy 电话 13912345678")  # allowlist-secret
    assert decision.action == "reject"


def test_g3_plain_numbers_are_not_pii():
    from mase.governance.admission_gate import scan_sensitive

    # 订单号/金额等长数字不应误伤(手机号断言了前后无数字)
    assert scan_sensitive("订单 202607040013912345678999").action == "pass"
    assert scan_sensitive("总额 12,340.00").action == "pass"


# ---------- G5 TTL ----------

def test_g5_tool_state_gets_default_ttl():
    from mase.governance.admission_gate import DEFAULT_TTL_DAYS, apply_ttl_policy

    contract = _contract(claim_type="tool_state", observed_at="2026-07-04T00:00:00Z")
    out = apply_ttl_policy(contract)
    assert out.valid_to == "2026-07-11T00:00:00Z"
    assert DEFAULT_TTL_DAYS == 7


def test_g5_explicit_valid_to_is_kept():
    from mase.governance.admission_gate import apply_ttl_policy

    contract = _contract(claim_type="tool_state", valid_to="2026-08-01T00:00:00Z")
    assert apply_ttl_policy(contract).valid_to == "2026-08-01T00:00:00Z"


def test_g5_non_tool_state_untouched():
    from mase.governance.admission_gate import apply_ttl_policy

    contract = _contract(claim_type="preference")
    out = apply_ttl_policy(contract)
    assert out.valid_to is None and out == contract


# ---------- review_actions 表 ----------

def test_review_actions_table_created(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "gate.db"))
    from contextlib import closing

    from mase_tools.memory.db_core import get_connection

    with closing(get_connection()) as conn:
        names = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")
        }
    assert "review_actions" in names
    assert "idx_review_actions_fact" in names
