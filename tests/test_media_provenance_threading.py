"""事实/流水账写路径携带 source_media_id 的行为测试(白盒溯源链)。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate_db(tmp_path, monkeypatch) -> Path:
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "prov.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    return db


def test_write_interaction_carries_source_media_id(tmp_path, monkeypatch):
    db = _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_register_media_asset, mase2_write_interaction

    media_id = mase2_register_media_asset(
        "d" * 64, source_uri="scan.png", media_type="image/png"
    )
    mase2_write_interaction("ingest::test", "system", "OCR full text here", source_media_id=media_id)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM memory_log WHERE thread_id = 'ingest::test'").fetchone()
    conn.close()
    assert row["source_media_id"] == media_id


def test_upsert_fact_carries_source_media_id(tmp_path, monkeypatch):
    db = _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_register_media_asset, mase2_upsert_fact

    media_id = mase2_register_media_asset("e" * 64, source_uri=None, media_type="application/pdf")
    mase2_upsert_fact(
        "finance_budget", "invoice_total", "4200 EUR",
        reason=f"media_extraction:{'e' * 64}", source_media_id=media_id,
    )

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM entity_state WHERE category='finance_budget' AND entity_key='invoice_total'"
    ).fetchone()
    conn.close()
    assert row["source_media_id"] == media_id
    assert row["source_reason"].startswith("media_extraction:")


def test_plain_text_path_unaffected(tmp_path, monkeypatch):
    """特征钉:不传 source_media_id 时列为 NULL,原有行为不变。"""
    db = _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_upsert_fact, mase2_write_interaction

    mase2_write_interaction("t1", "user", "hello")
    mase2_upsert_fact("user_preferences", "lang", "zh")

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    log = conn.execute("SELECT source_media_id FROM memory_log WHERE thread_id='t1'").fetchone()
    fact = conn.execute("SELECT source_media_id FROM entity_state WHERE entity_key='lang'").fetchone()
    conn.close()
    assert log["source_media_id"] is None
    assert fact["source_media_id"] is None


def test_provenance_facade_returns_chain(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import (
        mase2_get_media_provenance,
        mase2_record_extraction,
        mase2_register_media_asset,
    )

    media_id = mase2_register_media_asset("f" * 64, source_uri="a.pdf", media_type="application/pdf")
    mase2_record_extraction(
        media_id, extractor_name="vision", model_name="qwen2.5vl:7b",
        extractor_version="1", full_text="text", result_json="{}",
    )
    chain = mase2_get_media_provenance(media_id)
    assert chain["asset"]["sha256"] == "f" * 64
    assert len(chain["extractions"]) == 1


def test_migration_adds_columns_to_existing_db(tmp_path, monkeypatch):
    """旧库(无新列)打开后自动获得 source_media_id 列,旧行不变。"""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE memory_log (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, role TEXT, content TEXT)"
    )
    conn.execute("INSERT INTO memory_log (thread_id, role, content) VALUES ('old', 'user', 'legacy row')")
    conn.commit()
    conn.close()

    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    from mase_tools.memory.api import mase2_write_interaction

    mase2_write_interaction("new", "user", "new row")

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_log)")}
    old = conn.execute("SELECT content FROM memory_log WHERE thread_id='old'").fetchone()
    conn.close()
    assert "source_media_id" in cols
    assert old["content"] == "legacy row"


def test_pk_rebuild_path_keeps_source_media_id_column(tmp_path, monkeypatch):
    """旧库 entity_state 主键未 scoped 时会触发重建;重建后新列必须仍在,
    且同进程内的 upsert 不因缺列崩溃(回归钉:重建 CREATE 曾漏列)。"""
    db = tmp_path / "legacy_pk.db"
    conn = sqlite3.connect(db)
    # 真实历史版式:MASE 2.0 早期 entity_state(未 scoped 的双列 PK)。
    conn.execute(
        """
        CREATE TABLE entity_state (
            category TEXT,
            entity_key TEXT,
            entity_value TEXT,
            source_log_id INTEGER,
            source_reason TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (category, entity_key)
        )
        """
    )
    conn.execute(
        "INSERT INTO entity_state (category, entity_key, entity_value) VALUES ('user_preferences', 'lang', 'zh')"
    )
    conn.commit()
    conn.close()

    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    from mase_tools.memory.api import mase2_register_media_asset, mase2_upsert_fact

    media_id = mase2_register_media_asset("9" * 64, source_uri=None, media_type="image/png")
    mase2_upsert_fact("general_facts", "doc_x", "v", source_media_id=media_id)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    migrated = conn.execute("SELECT entity_value FROM entity_state WHERE entity_key='lang'").fetchone()
    new_fact = conn.execute("SELECT source_media_id FROM entity_state WHERE entity_key='doc_x'").fetchone()
    conn.close()
    assert migrated["entity_value"] == "zh"  # 旧数据在重建中保留
    assert new_fact["source_media_id"] == media_id
