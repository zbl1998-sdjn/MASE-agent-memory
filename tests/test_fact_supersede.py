"""Tests for the Mem0-style auto-correction / supersede pipeline."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mase_tools.memory import db_core
from mase_tools.memory.correction_detector import (
    detect_correction,
    extract_keywords_for_supersede,
)


@pytest.fixture()
def fresh_db(monkeypatch: pytest.MonkeyPatch) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "mem.db"
    monkeypatch.setattr(db_core, "DB_PATH", tmp)
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
