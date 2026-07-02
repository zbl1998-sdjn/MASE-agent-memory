"""media_asset / media_extraction 溯源表 CRUD 行为测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "media.db"))


def test_register_media_asset_is_idempotent_per_hash(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.media_records import get_media_asset, register_media_asset

    first = register_media_asset("a" * 64, source_uri="docs/inv.png", media_type="image/png", byte_size=123)
    second = register_media_asset("a" * 64, source_uri="docs/other.png", media_type="image/png", byte_size=123)
    assert first == second  # 同哈希同 scope 幂等

    row = get_media_asset(first)
    assert row is not None
    assert row["sha256"] == "a" * 64
    assert row["media_type"] == "image/png"
    assert get_media_asset(sha256="a" * 64)["id"] == first


def test_register_media_asset_scoped_by_tenant(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.media_records import register_media_asset

    base = register_media_asset("b" * 64, source_uri=None, media_type="application/pdf")
    other = register_media_asset("b" * 64, source_uri=None, media_type="application/pdf", tenant_id="acme")
    assert base != other  # 不同租户不共享资产行


def test_record_and_find_extraction_and_provenance(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.media_records import (
        find_extraction,
        get_media_provenance,
        record_extraction,
        register_media_asset,
    )

    media_id = register_media_asset("c" * 64, source_uri="scan.pdf", media_type="application/pdf", page_count=2)
    assert find_extraction(media_id, extractor_name="vision", extractor_version="1") is None

    ext_id = record_extraction(
        media_id,
        extractor_name="vision",
        model_name="qwen2.5vl:7b",
        extractor_version="1",
        full_text="Invoice total 4200",
        result_json=json.dumps({"facts": []}),
    )
    assert isinstance(ext_id, int)

    found = find_extraction(media_id, extractor_name="vision", extractor_version="1")
    assert found is not None and found["id"] == ext_id and found["full_text"] == "Invoice total 4200"

    chain = get_media_provenance(media_id)
    assert chain["asset"]["sha256"] == "c" * 64
    assert [e["id"] for e in chain["extractions"]] == [ext_id]
