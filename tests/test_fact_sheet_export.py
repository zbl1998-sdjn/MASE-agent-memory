"""fact sheet 导出行为测试(P0 T5):markdown 与库内容一致,三节分状态。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOURCE_TEXT = "采购单 PO-2026\n供应商 宏远贸易\n总额 $12,340.00\n修订总额 $13,000.00"


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "sheets.db"))


def _propose(entity_id, predicate, value, evidence, **overrides):
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    contract = FactContract(
        fact_id=new_fact_id(),
        entity_id=entity_id,
        claim_type=overrides.pop("claim_type", "document_claim"),
        subject="general_facts",
        predicate=predicate,
        object_value=value,
        confidence=0.9,
        observed_at="2026-07-04T00:00:00Z",
        qualifiers={"scope": "docs/po.pdf"},
    )
    return propose_fact(
        contract,
        evidence,
        source_type="media_extraction",
        source_id="17",
        trust_level=4,
        source_full_text=SOURCE_TEXT,
        **overrides,
    )


def _seed(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    # entity A:active(经一次 supersede)+ quarantined
    _propose("media:aaa111", "order_total", "$12,340.00", "总额 $12,340.00")
    _propose("media:aaa111", "order_total", "$13,000.00", "修订总额 $13,000.00")
    _propose("media:aaa111", "shipping_fee", "$99.00", "运费不在原文里")
    # entity B:一条 active
    _propose("media:bbb222", "supplier", "宏远贸易", "供应商 宏远贸易")


def test_export_writes_one_sheet_per_entity(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    from scripts.export_fact_sheets import export_fact_sheets

    out = tmp_path / "sheets"
    paths = export_fact_sheets(out_dir=out)
    names = sorted(p.name for p in paths)
    assert names == ["media_aaa111.md", "media_bbb222.md"]
    assert all(p.parent == out for p in paths)


def test_sheet_sections_match_database(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    from scripts.export_fact_sheets import export_fact_sheets

    paths = export_fact_sheets(out_dir=tmp_path / "sheets")
    sheet = next(p for p in paths if p.name == "media_aaa111.md").read_text(encoding="utf-8")

    # front-matter
    assert sheet.startswith("---\n")
    assert "schema_version: fact_contract.v1" in sheet
    assert "entity_id: media:aaa111" in sheet
    assert "generated_at:" in sheet

    # 三节齐全且顺序固定
    active_at = sheet.index("## Active")
    superseded_at = sheet.index("## Superseded")
    quarantined_at = sheet.index("## Quarantined")
    assert active_at < superseded_at < quarantined_at

    active_section = sheet[active_at:superseded_at]
    superseded_section = sheet[superseded_at:quarantined_at]
    quarantined_section = sheet[quarantined_at:]
    assert "$13,000.00" in active_section  # 新值 active
    assert "$12,340.00" in superseded_section  # 旧值被 supersede
    assert "shipping_fee" in quarantined_section  # 假证据进隔离
    assert "运费不在原文里" in quarantined_section  # 隔离证据留痕可读

    # 证据可反查:来源与 span 出现在 active 行
    assert "media_extraction:17" in active_section
    assert "observed_at" in sheet or "2026-07-04" in sheet


def test_entity_filter_exports_single_sheet(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    from scripts.export_fact_sheets import export_fact_sheets

    paths = export_fact_sheets(out_dir=tmp_path / "one", entity_id="media:bbb222")
    assert [p.name for p in paths] == ["media_bbb222.md"]
    content = paths[0].read_text(encoding="utf-8")
    assert "宏远贸易" in content


def test_empty_database_exports_nothing(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from scripts.export_fact_sheets import export_fact_sheets

    assert export_fact_sheets(out_dir=tmp_path / "none") == []


def test_pipe_in_value_does_not_break_table(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact
    from scripts.export_fact_sheets import export_fact_sheets

    source = "备注 A|B 型号"
    propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="media:ccc333",
            claim_type="document_claim",
            subject="general_facts",
            predicate="model_code",
            object_value="A|B",
            confidence=0.9,
            observed_at="2026-07-04T00:00:00Z",
        ),
        "A|B",
        source_type="media_extraction",
        source_id="9",
        trust_level=4,
        source_full_text=source,
    )
    (sheet_path,) = export_fact_sheets(out_dir=tmp_path / "pipe")
    content = sheet_path.read_text(encoding="utf-8")
    assert "A\\|B" in content  # 表格内竖线已转义
