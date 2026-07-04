"""Answer Claim Verifier gold set 测试(P3 T1/T2):逐句映射、violation、revise/refuse、审计。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOURCE_TEXT = "会议纪要:预算 800 元。低信源说预算 300 元。旧预算 500 元。联系人电话 13912345678"
KEYWORDS = ["800", "300", "500", "13912345678"]


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "verify.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    return db


def _propose(predicate, value, evidence, *, trust=5):
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    return propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="user:default",
            claim_type="project_fact",
            subject="project_facts",
            predicate=predicate,
            object_value=value,
            confidence=0.9,
            observed_at="2026-07-04T00:00:00Z",
        ),
        evidence,
        source_type="memory_log",
        source_id="1",
        trust_level=trust,
        source_full_text=SOURCE_TEXT,
    )


def _seed_gold(tmp_path, monkeypatch):
    """gold set 种子:superseded 500 → active 800;冲突方 300(隔离);PII 电话(隔离)。"""
    db = _isolate_db(tmp_path, monkeypatch)
    _propose("budget", "500 元", "旧预算 500 元")
    active = _propose("budget", "800 元", "预算 800 元")
    _propose("budget", "300 元", "低信源说预算 300 元", trust=1)
    _propose("contact_phone", "13912345678", "联系人电话 13912345678")
    return db, active


def _verify(answer, keywords=None):
    from mase.governance.claim_verifier import verify_answer
    from mase.governance.evidence_pack import compile_evidence_pack

    pack = compile_evidence_pack("预算多少?", keywords or KEYWORDS)
    return verify_answer(answer, pack)


def test_supported_sentence_maps_to_fact(tmp_path, monkeypatch):
    _, active = _seed_gold(tmp_path, monkeypatch)
    audit = _verify("目前预算是 800 元。这与去年方案不同。")
    tags = {s["tag"] for s in audit.spans}
    supported = [s for s in audit.spans if s["tag"] == "SUPPORTED_BY_MEMORY"]
    assert supported and active.fact_id in supported[0]["fact_ids"]
    assert "UNTAGGED" in tags  # 非记忆句如实不判
    assert audit.verdict == "pass"
    assert audit.violations == ()


def test_stale_value_is_flagged(tmp_path, monkeypatch):
    _seed_gold(tmp_path, monkeypatch)
    audit = _verify("目前预算是 500 元。")
    (span,) = (s for s in audit.spans if s["tag"] == "STALE")
    assert span["violation"]
    assert audit.verdict in ("revise", "refuse")


def test_old_and_new_value_comparison_is_not_violation(tmp_path, monkeypatch):
    _seed_gold(tmp_path, monkeypatch)
    audit = _verify("预算从 500 元上调为 800 元。")
    assert not any(s["tag"] == "STALE" and s["violation"] for s in audit.spans)
    assert audit.verdict == "pass"


def test_one_sided_conflict_value_is_violation(tmp_path, monkeypatch):
    _seed_gold(tmp_path, monkeypatch)
    audit = _verify("预算是 300 元。")
    conflicting = [s for s in audit.spans if s["tag"] == "CONFLICTING"]
    assert conflicting and conflicting[0]["violation"]


def test_reported_conflict_is_compliant(tmp_path, monkeypatch):
    _seed_gold(tmp_path, monkeypatch)
    audit = _verify("关于预算存在冲突:一说 800 元,一说 300 元,以复核为准。")
    conflicting = [s for s in audit.spans if s["tag"] == "CONFLICTING"]
    assert conflicting and not conflicting[0]["violation"]
    assert audit.verdict == "pass"


def test_quarantined_value_is_unsupported(tmp_path, monkeypatch):
    _seed_gold(tmp_path, monkeypatch)
    audit = _verify("他的电话是 13912345678。")
    (span,) = (s for s in audit.spans if s["tag"] == "UNSUPPORTED_MEMORY_CLAIM")
    assert span["violation"]


def test_revise_annotates_every_violation(tmp_path, monkeypatch):
    _seed_gold(tmp_path, monkeypatch)
    from mase.governance.claim_verifier import revise_answer

    audit = _verify("目前预算是 500 元。联系电话 13912345678。今天天气不错。")
    revised = revise_answer(audit)
    assert revised.count("〔MASE治理:") == 2  # 两个 violation 句都被显式标注
    assert "今天天气不错。" in revised  # 无违规句原样保留
    # unsupported 未标注率降为 0:每个 violation 句均带标注
    for span in audit.spans:
        if span["violation"]:
            assert span["text"] in revised


def test_refuse_outputs_unknown_instead_of_fabrication(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)  # 空库:Verified 必为空
    from mase.governance.claim_verifier import revise_answer
    from mase.governance.evidence_pack import compile_evidence_pack
    from mase.governance.claim_verifier import verify_answer

    _propose("budget", "800 元", "预算 800 元")  # 有一条,但答案引用的是隔离电话
    _propose("contact_phone", "13912345678", "联系人电话 13912345678")
    pack = compile_evidence_pack("电话多少?", ["13912345678", "无覆盖词zzz"])
    audit = verify_answer("电话是 13912345678。", pack)
    assert audit.verdict == "refuse"  # Verified 为空且有 violation
    revised = revise_answer(audit)
    assert "13912345678" not in revised.split("原答案")[0]  # 拒答正文不复述编造值
    assert "无覆盖词zzz" in revised  # unknowns 显性输出


def test_audit_row_persisted_with_trace(tmp_path, monkeypatch):
    db, _ = _seed_gold(tmp_path, monkeypatch)
    audit = _verify("目前预算是 800 元。")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM answer_audits").fetchone()
    pack_row = conn.execute(
        "SELECT trace_id FROM context_packs WHERE trace_id = ?", (row["trace_id"],)
    ).fetchone()
    conn.close()
    assert row["verdict"] == "pass" and row["audit_id"] == audit.audit_id
    assert pack_row is not None  # trace 链回 context_packs
    spans = json.loads(row["spans_json"])
    assert spans and spans[0]["tag"]


def test_facade_returns_full_result(tmp_path, monkeypatch):
    _seed_gold(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_verify_answer

    result = mase2_verify_answer("预算多少?", KEYWORDS, "目前预算是 500 元。")
    assert result["verdict"] in ("revise", "refuse")
    assert "〔MASE治理:" in result["revised_text"]
    assert result["trace_id"].startswith("tr_")
    assert result["violations"]
