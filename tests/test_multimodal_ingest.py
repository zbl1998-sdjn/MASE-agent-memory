"""摄取管线端到端(假抽取器,无真模型):溯源、幂等、隔离、越界拒绝。"""
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
    """确定性抽取器:全文=文件名标记,一条事实;可指定对某文件抛错。"""

    name = "fake"
    version = "1"

    def __init__(self, *, boom_on: str | None = None):
        self.boom_on = boom_on
        self.extract_count = 0

    def supports(self, media_type: str) -> bool:
        return True

    def extract(self, asset, payload) -> ExtractionResult:
        self.extract_count += 1
        if self.boom_on and self.boom_on in str(asset.source_uri):
            raise RuntimeError("simulated model failure")
        tag = Path(str(asset.source_uri)).stem
        return ExtractionResult(
            full_text=f"fulltext-of-{tag} unique-token-{tag}",
            candidate_facts=(
                CandidateFact("general_facts", f"doc_{tag}", f"value-{tag}", 0.8, f"unique-token-{tag}"),
            ),
            extractor_name=self.name, model_name="fake-model", extractor_version=self.version,
            warnings=(),
        )


def _setup(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "ingest.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    docs = tmp_path / "docs"
    docs.mkdir()
    assets = tmp_path / "assets"
    return db, docs, assets


def test_ingest_writes_facts_with_full_provenance_chain(tmp_path, monkeypatch):
    db, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "invoice.png").write_bytes(b"\x89PNG-invoice-bytes")
    from mase.multimodal.ingest import ingest_folder
    from mase_tools.memory.api import mase2_get_media_provenance, mase2_search_memory

    report = ingest_folder(docs, extractor=FakeExtractor(), asset_root=assets)
    assert report.processed == ("invoice.png",)
    assert report.extractions == 1 and report.facts_written == 1
    assert report.infra_errors == () and report.skipped == ()

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    fact = conn.execute("SELECT * FROM entity_state WHERE entity_key='doc_invoice'").fetchone()
    assert fact["source_media_id"] is not None
    assert fact["source_reason"].startswith("media_extraction:")
    log = conn.execute("SELECT * FROM memory_log WHERE source_media_id = ?", (fact["source_media_id"],)).fetchone()
    assert "unique-token-invoice" in log["content"]
    conn.close()

    chain = mase2_get_media_provenance(fact["source_media_id"])
    assert chain["asset"]["source_uri"].endswith("invoice.png")
    assert chain["extractions"][0]["model_name"] == "fake-model"
    # 资产文件真实落盘
    sha = chain["asset"]["sha256"]
    assert (assets / sha[:2] / f"{sha}.png").read_bytes() == b"\x89PNG-invoice-bytes"
    # 召回链:全文可被现有搜索命中
    hits = mase2_search_memory(["unique-token-invoice"], limit=5)
    assert any("unique-token-invoice" in str(h.get("content", "")) for h in hits)


def test_ingest_is_idempotent_and_force_reextracts(tmp_path, monkeypatch):
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "a.png").write_bytes(b"same-bytes")
    from mase.multimodal.ingest import ingest_folder

    fake = FakeExtractor()
    ingest_folder(docs, extractor=fake, asset_root=assets)
    report2 = ingest_folder(docs, extractor=fake, asset_root=assets)
    assert fake.extract_count == 1  # 第二遍同 (hash, extractor, version) 跳过
    assert report2.skipped and report2.skipped[0]["reason"] == "already_extracted"

    ingest_folder(docs, extractor=fake, asset_root=assets, force=True)
    assert fake.extract_count == 2


def test_per_file_isolation_on_extractor_failure(tmp_path, monkeypatch):
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "bad.png").write_bytes(b"bad-bytes")
    (docs / "good.png").write_bytes(b"good-bytes")
    from mase.multimodal.ingest import ingest_folder

    report = ingest_folder(docs, extractor=FakeExtractor(boom_on="bad"), asset_root=assets)
    assert report.processed == ("good.png",)
    assert len(report.infra_errors) == 1
    assert report.infra_errors[0]["file"] == "bad.png"
    assert "simulated model failure" in report.infra_errors[0]["error"]


def test_non_allowlisted_and_escaping_files_are_skipped(tmp_path, monkeypatch):
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "note.txt").write_text("not media")
    (docs / "ok.png").write_bytes(b"ok")
    from mase.multimodal.ingest import ingest_folder

    report = ingest_folder(docs, extractor=FakeExtractor(), asset_root=assets)
    assert report.processed == ("ok.png",)
    assert any(s["file"] == "note.txt" and s["reason"] == "unsupported_media" for s in report.skipped)


def test_mixed_folder_dispatches_by_media_type(tmp_path, monkeypatch):
    """图像走 vision、音频走 audio,一次批处理各归其位(全假抽取,不碰真模型)。"""
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "pic.png").write_bytes(b"img-bytes")
    (docs / "talk.wav").write_bytes(b"RIFF-bytes")

    from mase.multimodal import ingest as ingest_mod
    from mase.multimodal.ingest import ingest_folder

    class _StubVision:
        name, version = "vision", "1"

        def supports(self, media_type):
            return not media_type.startswith("audio/")

        def extract(self, asset, payload):
            return FakeExtractor().extract(asset, payload)

    class _StubAudio:
        name, version = "audio", "1"
        seen = []

        def supports(self, media_type):
            return media_type.startswith("audio/")

        def extract(self, asset, payload):
            _StubAudio.seen.append(asset.media_type)
            assert payload.audio is not None
            return FakeExtractor().extract(asset, payload)

    monkeypatch.setattr(
        ingest_mod, "_default_extractors", lambda mode, whisper_model: [_StubVision(), _StubAudio()]
    )
    report = ingest_folder(docs, asset_root=assets)
    assert sorted(report.processed) == ["pic.png", "talk.wav"]
    assert _StubAudio.seen == ["audio/wav"]


def test_no_extractor_supports_type_is_skipped(tmp_path, monkeypatch):
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "talk.wav").write_bytes(b"RIFF")

    from mase.multimodal import ingest as ingest_mod
    from mase.multimodal.ingest import ingest_folder

    class _OnlyVision:
        name, version = "vision", "1"

        def supports(self, media_type):
            return media_type.startswith("image/")

        def extract(self, asset, payload):
            raise AssertionError("不应被调用")

    monkeypatch.setattr(ingest_mod, "_default_extractors", lambda mode, whisper_model: [_OnlyVision()])
    report = ingest_folder(docs, asset_root=assets)
    assert any(s["file"] == "talk.wav" and s["reason"] == "no_extractor" for s in report.skipped)
