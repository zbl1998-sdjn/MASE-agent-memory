"""Evidence Pack 编译器测试(P2 T2):五节结构、无证据不注入、审计可回放。"""
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


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "pack.db"))
    return tmp_path / "pack.db"


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


def _seed(tmp_path, monkeypatch):
    db = _isolate_db(tmp_path, monkeypatch)
    old = _propose("budget", "500 元", "旧预算 500 元")          # → superseded
    active = _propose("budget", "800 元", "预算 800 元")          # active
    conflicted = _propose("budget", "300 元", "低信源说预算 300 元", trust=1)  # 冲突隔离
    return db, old, active, conflicted


def _compile(question="现在预算是多少?", keywords=None, **kwargs):
    from mase.governance.evidence_pack import compile_evidence_pack

    return compile_evidence_pack(
        question, keywords if keywords is not None else ["800", "300", "500", "未知词xyz"], **kwargs
    )


def test_verified_only_active_with_span(tmp_path, monkeypatch):
    _, old, active, conflicted = _seed(tmp_path, monkeypatch)
    pack = _compile()
    verified_ids = [v["fact_id"] for v in pack.verified]
    assert verified_ids == [active.fact_id]  # superseded/quarantined 不入 Verified
    entry = pack.verified[0]
    assert "800 元" in entry["claim"]
    assert entry["why_selected"]
    assert entry["evidence_ref"]  # 带 span 的来源引用
    assert pack.trace_id.startswith("tr_")


def test_conflict_section_shows_both_sides(tmp_path, monkeypatch):
    _, _, active, conflicted = _seed(tmp_path, monkeypatch)
    pack = _compile()
    assert pack.conflicts
    sides = {s["fact_id"] for c in pack.conflicts for s in c["sides"]}
    assert {active.fact_id, conflicted.fact_id} <= sides
    assert any("冲突" in c["warning"] for c in pack.conflicts)


def test_unknowns_and_do_not_assume(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    pack = _compile()
    assert any("未知词xyz" in u for u in pack.unknowns)
    assert any("300 元" in d and "quarantined" in d for d in pack.do_not_assume)


def test_evidence_less_active_is_excluded_with_warning(tmp_path, monkeypatch):
    db, _, active, _ = _seed(tmp_path, monkeypatch)
    # 模拟脏数据:把 active 事实的 span 直接置 NULL(绕过 API 的攻击面演练)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        UPDATE evidence_spans SET span_start = NULL, span_end = NULL
        WHERE evidence_id IN (SELECT evidence_id FROM fact_evidence WHERE fact_id = ?)
        """,
        (active.fact_id,),
    )
    conn.commit()
    conn.close()

    pack = _compile()
    assert all(v["fact_id"] != active.fact_id for v in pack.verified)
    assert any(active.fact_id in w for w in pack.warnings)


def test_audit_rows_replayable(tmp_path, monkeypatch):
    db, *_ = _seed(tmp_path, monkeypatch)
    pack1 = _compile()
    pack2 = _compile()
    assert pack1.trace_id != pack2.trace_id  # 重复 compile 各自留痕

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    runs = conn.execute("SELECT * FROM retrieval_runs ORDER BY created_at").fetchall()
    packs = conn.execute("SELECT * FROM context_packs ORDER BY created_at").fetchall()
    conn.close()
    assert len(runs) == 2 and len(packs) == 2
    assert {r["trace_id"] for r in runs} == {pack1.trace_id, pack2.trace_id}
    assert runs[0]["trace_id"] == packs[0]["trace_id"]
    candidates = json.loads(runs[0]["candidates_json"])
    assert candidates and "score_breakdown" in candidates[0]  # 候选打分全量可回放
    assert json.loads(packs[0]["fact_ids_json"])


def test_markdown_render_has_all_sections(tmp_path, monkeypatch):
    _, _, active, _ = _seed(tmp_path, monkeypatch)
    from mase.governance.evidence_pack import render_markdown

    pack = _compile()
    text = render_markdown(pack)
    for heading in (
        "# Memory Evidence Pack",
        "## User Question",
        "## Verified Facts",
        "## Conflicts",
        "## Unknowns",
        "## Do Not Assume",
        "## Answer Rules",
    ):
        assert heading in text, heading
    assert "现在预算是多少?" in text
    assert active.fact_id in text
    assert pack.token_estimate == len(text) // 4


def test_top_k_limits_verified(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    for i in range(5):
        _propose(f"item_{i}", f"共有词 {i} 号", "预算 800 元")
    pack = _compile(keywords=["共有词"], top_k=2)
    assert len(pack.verified) <= 2
