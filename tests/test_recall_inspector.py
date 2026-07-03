"""门面与 recall inspector CLI 测试(P2 T3)。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "inspector.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    return db


def _seed():
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    return propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="user:default",
            claim_type="project_fact",
            subject="project_facts",
            predicate="budget",
            object_value="800 元",
            confidence=0.9,
            observed_at="2026-07-04T00:00:00Z",
        ),
        "预算 800 元",
        source_type="memory_log",
        source_id="1",
        trust_level=5,
        source_full_text="会议纪要:预算 800 元。",
    )


def test_facade_returns_pack_dict(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    fact = _seed()
    from mase_tools.memory.api import mase2_compile_evidence_pack

    result = mase2_compile_evidence_pack("预算多少?", ["800"])
    assert isinstance(result, dict)
    assert result["verified"][0]["fact_id"] == fact.fact_id
    assert "## Verified Facts" in result["markdown"]
    assert result["trace_id"].startswith("tr_")


def test_cli_prints_three_sections(tmp_path, monkeypatch, capsys):
    _isolate_db(tmp_path, monkeypatch)
    fact = _seed()
    from scripts.inspect_recall import main

    code = main(["--keywords", "800,不存在词", "--question", "预算多少?"])
    out = capsys.readouterr().out
    assert code == 0
    assert "=== PLAN ===" in out
    assert "=== CANDIDATES ===" in out
    assert "=== PACK ===" in out
    assert fact.fact_id in out
    assert "score_breakdown" in out or "why" in out
    assert "尚无记忆事实覆盖" in out


def test_cli_db_option_overrides(tmp_path, monkeypatch, capsys):
    db = _isolate_db(tmp_path, monkeypatch)
    _seed()
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "other.db"))  # 环境指向别处
    from scripts.inspect_recall import main

    code = main(["--keywords", "800", "--db", str(db)])
    out = capsys.readouterr().out
    assert code == 0
    assert "budget" in out  # 从 --db 指定库读到种子事实
