"""双写接线行为测试(P0 T4):ingest 与 mase2 门面 → 治理层 facts。

约束:entity_state 读路径零变化;治理层失败不打断摄取(best-effort 留痕);
旧签名 mase2_upsert_fact 零破坏(不产 governance fact)。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.extractor import CandidateFact, ExtractionResult


class FakeExtractor:
    """确定性抽取器;evidence 可配置为原文内/外,以驱动 active/quarantined 分支。"""

    name = "fake"
    version = "1"

    def __init__(self, *, evidence: str | None = None):
        self.evidence = evidence

    def supports(self, media_type: str) -> bool:
        return True

    def extract(self, asset, payload) -> ExtractionResult:
        tag = Path(str(asset.source_uri)).stem
        evidence = self.evidence if self.evidence is not None else f"unique-token-{tag}"
        return ExtractionResult(
            full_text=f"fulltext-of-{tag} unique-token-{tag}",
            candidate_facts=(
                CandidateFact("general_facts", f"doc_{tag}", f"value-{tag}", 0.8, evidence),
            ),
            extractor_name=self.name, model_name="fake-model", extractor_version=self.version,
            warnings=(),
        )


def _setup(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "dual.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    docs = tmp_path / "docs"
    docs.mkdir()
    return db, docs, tmp_path / "assets"


def _facts_rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM facts")]
    conn.close()
    return rows


def test_ingest_dual_writes_active_fact_with_located_span(tmp_path, monkeypatch):
    db, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "invoice.png").write_bytes(b"\x89PNG-invoice-bytes")
    from mase.multimodal.ingest import ingest_folder

    report = ingest_folder(docs, extractor=FakeExtractor(), asset_root=assets)
    assert report.processed == ("invoice.png",)
    assert report.facts_written == 1
    assert report.facts_governed == 1
    assert report.governance_warnings == ()

    (fact,) = _facts_rows(db)
    assert fact["status"] == "active"
    assert fact["claim_type"] == "document_claim"
    assert fact["subject"] == "general_facts"
    assert fact["predicate"] == "doc_invoice"
    assert fact["object"] == "value-invoice"
    assert '"scope"' in fact["qualifiers_json"]

    # entity_id 锚定媒体资产;证据反查 media_extraction 全文偏移命中。
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    asset = conn.execute("SELECT * FROM media_asset").fetchone()
    assert fact["entity_id"] == f"media:{asset['sha256'][:12]}"
    span = conn.execute(
        """
        SELECT es.* FROM evidence_spans es
        JOIN fact_evidence fe ON fe.evidence_id = es.evidence_id
        WHERE fe.fact_id = ?
        """,
        (fact["fact_id"],),
    ).fetchone()
    assert span["source_type"] == "media_extraction"
    assert span["trust_level"] == 4
    extraction = conn.execute(
        "SELECT * FROM media_extraction WHERE id = ?", (int(span["source_id"]),)
    ).fetchone()
    assert extraction["full_text"][span["span_start"] : span["span_end"]] == "unique-token-invoice"
    # entity_state 兼容投影照旧(读路径零变化)。
    entity = conn.execute("SELECT * FROM entity_state WHERE entity_key='doc_invoice'").fetchone()
    assert entity is not None and entity["source_media_id"] is not None
    conn.close()


def test_ingest_fabricated_evidence_lands_quarantined(tmp_path, monkeypatch):
    db, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "scan.png").write_bytes(b"\x89PNG-scan-bytes")
    from mase.multimodal.ingest import ingest_folder

    report = ingest_folder(
        docs, extractor=FakeExtractor(evidence="不在底稿里的引文"), asset_root=assets
    )
    assert report.facts_governed == 1  # 留痕也算治理覆盖

    (fact,) = _facts_rows(db)
    assert fact["status"] == "quarantined"
    # entity_state 双写不受影响(P0 兼容投影,准入门控是 P1)。
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM entity_state").fetchone()[0] == 1
    conn.close()


def test_governance_failure_does_not_break_ingest(tmp_path, monkeypatch):
    db, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "a.png").write_bytes(b"bytes-a")
    from mase.multimodal.ingest import ingest_folder

    def _boom(*args, **kwargs):
        raise RuntimeError("governance layer down")

    monkeypatch.setattr("mase.governance.fact_store.propose_fact", _boom)
    report = ingest_folder(docs, extractor=FakeExtractor(), asset_root=assets)
    assert report.processed == ("a.png",)  # 摄取主链路不受阻
    assert report.facts_written == 1
    assert report.infra_errors == ()
    assert report.facts_governed == 0
    assert len(report.governance_warnings) == 1
    assert "governance layer down" in report.governance_warnings[0]["error"]
    assert _facts_rows(db) == []


def test_mase2_upsert_fact_old_signature_is_untouched(tmp_path, monkeypatch):
    db, _docs, _assets = _setup(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_upsert_fact

    message = mase2_upsert_fact("prefs", "editor", "vim", reason="user said so")
    assert message.startswith("Success")
    assert _facts_rows(db) == []  # 旧调用方不产 governance fact(零破坏)


def test_mase2_upsert_fact_with_full_evidence_dual_writes(tmp_path, monkeypatch):
    db, _docs, _assets = _setup(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_get_facts, mase2_upsert_fact

    source = "会议纪要:下季度预算定为 80 万元,负责人张三。"
    message = mase2_upsert_fact(
        "project_facts",
        "q3_budget",
        "80 万元",
        reason="notetaker",
        evidence_text="预算定为 80 万元",
        evidence_source_type="memory_log",
        evidence_source_id="123",
        evidence_trust_level=5,
        evidence_full_text=source,
    )
    assert message.startswith("Success")

    (fact,) = _facts_rows(db)
    assert fact["status"] == "active"
    assert fact["subject"] == "project_facts" and fact["predicate"] == "q3_budget"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    span = conn.execute("SELECT * FROM evidence_spans").fetchone()
    assert span["source_type"] == "memory_log" and span["trust_level"] == 5
    assert source[span["span_start"] : span["span_end"]] == "预算定为 80 万元"
    conn.close()
    # entity_state 照旧可读(注意:entity_state 会把未知 category 归一化,
    # 故不按 category 过滤;governance facts 的 subject 保留调用方原值)
    assert any(f.get("entity_key") == "q3_budget" for f in mase2_get_facts())


def test_mase2_upsert_fact_partial_evidence_params_skip_dual_write(tmp_path, monkeypatch):
    db, _docs, _assets = _setup(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_upsert_fact

    mase2_upsert_fact("prefs", "theme", "dark", evidence_text="只有引文没有全文")
    assert _facts_rows(db) == []  # 给齐才双写
