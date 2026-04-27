"""Tests for the Mem0-style auto-correction / supersede pipeline."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mase_tools.memory import db_core
from mase_tools.memory.correction_detector import (
    detect_correction,
    extract_keywords_for_supersede,
)
from mase import BenchmarkNotetaker


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tmp = (tmp_path / "mem.db").resolve()
    monkeypatch.setenv("MASE_DB_PATH", str(tmp))
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db_core._SCHEMA_READY.discard(str(tmp))
    db_core.init_db()
    return tmp


def test_detector_english_actually() -> None:
    sig = detect_correction("Actually, my budget is 1200, not 800")
    assert sig.is_correction is True
    assert sig.matched_pattern is not None


def test_detector_chinese_correction() -> None:
    sig = detect_correction("我之前说错了, 我其实是28岁")
    assert sig.is_correction is True


def test_detector_no_false_positive_on_neutral() -> None:
    assert not detect_correction("My budget is 1200 yuan").is_correction
    assert not detect_correction("我今年28岁").is_correction


def test_extract_keywords_keeps_subject_after_actually() -> None:
    kws = extract_keywords_for_supersede(
        "Actually, my monthly food budget is 1200 yuan, not 800"
    )
    assert "budget" in kws
    assert "1200" in kws


def test_supersede_hides_old_entry(fresh_db: Path) -> None:
    from mase_tools.memory import api

    api.mase2_write_interaction("t", "user", "My monthly food budget is 800 yuan")
    api.mase2_upsert_fact("finance_budget", "monthly_food_budget", "800")

    r = api.mase2_correct_and_log(
        "t", "Actually, my monthly food budget is 1200 yuan, not 800"
    )
    assert r["is_correction"] is True
    assert r["superseded_count"] >= 1

    hits = api.mase2_search_memory(["800", "budget"])
    contents = " || ".join(h["content"] for h in hits)
    assert "1200" in contents
    # The old line saying "is 800 yuan" must NOT appear (only the correction's
    # mention of "not 800" is allowed)
    old_lines = [h["content"] for h in hits if "is 800" in h["content"]]
    assert old_lines == []


def test_history_is_recorded_on_value_change(fresh_db: Path) -> None:
    from mase_tools.memory import api

    api.mase2_upsert_fact("user_preferences", "age", "25")
    api.mase2_upsert_fact(
        "user_preferences", "age", "28", reason="user_correction", source_log_id=42
    )
    history = api.mase2_get_fact_history("user_preferences", "age")
    assert len(history) == 1
    h = history[0]
    assert h["old_value"] == "25"
    assert h["new_value"] == "28"
    assert h["supersede_reason"] == "user_correction"
    assert h["source_log_id"] == 42


def test_history_not_recorded_on_first_insert(fresh_db: Path) -> None:
    from mase_tools.memory import api

    api.mase2_upsert_fact("user_preferences", "age", "25")
    assert api.mase2_get_fact_history("user_preferences", "age") == []


def test_history_not_recorded_on_identical_value(fresh_db: Path) -> None:
    from mase_tools.memory import api

    api.mase2_upsert_fact("user_preferences", "age", "25")
    api.mase2_upsert_fact("user_preferences", "age", "25")
    assert api.mase2_get_fact_history("user_preferences", "age") == []


def test_chinese_supersede_end_to_end(fresh_db: Path) -> None:
    from mase_tools.memory import api

    api.mase2_write_interaction("t", "user", "我今年25岁")
    api.mase2_upsert_fact("user_preferences", "age", "25")

    r = api.mase2_correct_and_log("t", "我之前说错了, 我其实是28岁")
    assert r["is_correction"] is True
    api.mase2_upsert_fact(
        "user_preferences", "age", "28",
        reason="user_correction", source_log_id=r["new_log_id"],
    )

    facts = api.mase2_get_facts("user_preferences")
    assert facts[0]["entity_value"] == "28"

    history = api.mase2_get_fact_history("user_preferences", "age")
    assert history[0]["old_value"] == "25"
    assert history[0]["new_value"] == "28"


def test_latest_fact_wins_in_entity_recall(fresh_db: Path) -> None:
    from mase_tools.memory import api

    api.mase2_upsert_fact("finance_budget", "monthly_food_budget", "800", source_log_id=1)
    api.mase2_upsert_fact(
        "finance_budget",
        "monthly_food_budget",
        "1200",
        reason="user_correction",
        source_log_id=2,
    )

    hits = api.mase2_search_entity_facts(["budget", "food"])
    assert hits
    assert hits[0]["entity_value"] == "1200"
    assert hits[0]["source_log_id"] == 2
    assert all("800" not in hit["content"] for hit in hits)


def test_correction_supersede_then_facts_first_recall(fresh_db: Path) -> None:
    from mase_tools.memory import api

    old_log_id = db_core.add_event_log("t", "user", "My monthly food budget is 800 yuan")
    api.mase2_upsert_fact(
        "finance_budget",
        "monthly_food_budget",
        "800",
        source_log_id=old_log_id,
    )

    correction = api.mase2_correct_and_log(
        "t",
        "Actually, my monthly food budget is 1200 yuan, not 800",
    )
    api.mase2_upsert_fact(
        "finance_budget",
        "monthly_food_budget",
        "1200",
        reason="user_correction",
        source_log_id=correction["new_log_id"],
    )

    hits = api.mase2_facts_first_recall(["budget", "food"], limit=3)
    assert hits[0]["_source"] == "entity_state"
    assert hits[0]["entity_value"] == "1200"
    assert hits[0]["source_log_id"] == correction["new_log_id"]
    log_hits = [hit for hit in hits if hit.get("_source") == "memory_log"]
    assert log_hits
    assert any("1200" in hit["content"] for hit in log_hits)
    assert all("is 800 yuan" not in hit["content"] for hit in log_hits)


def test_benchmark_notetaker_facts_first_recall_keeps_provenance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = (tmp_path / "benchmark-memory.sqlite3").resolve()
    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db_core._SCHEMA_READY.discard(str(db_path))

    notetaker = BenchmarkNotetaker()
    notetaker.write(
        user_query="I live in Paris now.",
        assistant_response="",
        summary="User lives in Paris now.",
        thread_id="thread-a",
    )
    source_log_id = int(notetaker.fetch_recent_records(1)[0]["id"])
    db_core.upsert_entity_fact(
        "location_events",
        "current_city",
        "Paris",
        reason="fact_extractor",
        source_log_id=source_log_id,
    )

    hits = notetaker.search(["Paris", "live"], full_query="Where do I live?", limit=3)
    assert hits[0]["_source"] == "entity_state"
    assert hits[0]["entity_value"] == "Paris"
    assert hits[0]["source_log_id"] == source_log_id
    assert "I live in Paris now." in str(hits[0]["source_content"])
    assert any(hit.get("_source") == "memory_log" for hit in hits[1:])

    fact_sheet = notetaker.build_fact_sheet(hits)
    assert "src_log=" in fact_sheet
    assert "evidence=User: I live in Paris now." in fact_sheet


def test_old_benchmark_notetaker_db_gains_timestamp_and_still_works(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    db_path = (tmp_path / "old-bn.sqlite3").resolve()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT,
                role TEXT,
                content TEXT,
                summary TEXT,
                thread_label TEXT,
                topic_tokens TEXT,
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO memory_log (thread_id, role, content, summary, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "legacy-thread",
                "user",
                "User: I used to live in London.",
                "legacy row",
                "2024-01-02 03:04:05",
            ),
        )

    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db_core._SCHEMA_READY.discard(str(db_path))

    notetaker = BenchmarkNotetaker()

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_log)").fetchall()}
        assert "timestamp" in cols
        legacy_timestamp = conn.execute(
            "SELECT timestamp FROM memory_log WHERE id = 1"
        ).fetchone()[0]
    assert legacy_timestamp == "2024-01-02 03:04:05"

    notetaker.write(
        user_query="I live in Paris now.",
        assistant_response="",
        summary="User lives in Paris now.",
        thread_id="thread-a",
    )
    recent = notetaker.fetch_recent_records(2)
    assert recent[0]["event_timestamp"]
    assert recent[-1]["event_timestamp"] == "2024-01-02 03:04:05"

    source_log_id = int(recent[0]["id"])
    db_core.upsert_entity_fact(
        "location_events",
        "current_city",
        "Paris",
        reason="fact_extractor",
        source_log_id=source_log_id,
    )
    hits = notetaker.search(["Paris", "live"], full_query="Where do I live?", limit=3)
    assert hits[0]["_source"] == "entity_state"
    assert hits[0]["entity_value"] == "Paris"
    assert any(hit.get("_source") == "memory_log" for hit in hits[1:])


def test_current_state_fact_recall_prefers_latest_corrected_value(fresh_db: Path) -> None:
    from mase_tools.memory import api

    api.mase2_upsert_fact("user_preferences", "favorite_color", "blue")
    api.mase2_upsert_fact(
        "user_preferences",
        "favorite_color",
        "green",
        reason="user_correction",
        source_log_id=2,
    )

    facts = api.mase2_get_facts("user_preferences")
    favorite_color = next(row for row in facts if row["entity_key"] == "favorite_color")
    assert favorite_color["entity_value"] == "green"
    history = api.mase2_get_fact_history("user_preferences", "favorite_color")
    assert len(history) == 1
    assert history[0]["old_value"] == "blue"
    assert history[0]["new_value"] == "green"


def test_created_at_migration_avoids_alter_table_default_current_timestamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    db_path = (tmp_path / "legacy-created-at.sqlite3").resolve()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO memory_log (thread_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            ("legacy-thread", "user", "legacy row", "2024-02-03 04:05:06"),
        )

    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db_core._SCHEMA_READY.discard(str(db_path))

    db_core.init_db()

    with sqlite3.connect(db_path) as conn:
        table_info = {
            row[1]: row for row in conn.execute("PRAGMA table_info(memory_log)").fetchall()
        }
        created_at = conn.execute(
            "SELECT created_at FROM memory_log WHERE id = 1"
        ).fetchone()[0]

    assert "created_at" in table_info
    assert table_info["created_at"][4] is None
    assert created_at == "2024-02-03 04:05:06"
