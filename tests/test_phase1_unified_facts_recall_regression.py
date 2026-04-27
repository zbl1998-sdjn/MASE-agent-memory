from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase.benchmark_notetaker import BenchmarkNotetaker
from mase.topic_threads import derive_thread_context
from mase_tools.memory import api, db_core


@pytest.fixture()
def unified_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = (tmp_path / "phase1-unified.sqlite3").resolve()
    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    db_core._SCHEMA_READY.discard(str(db_path))
    return db_path


def test_latest_fact_wins_on_unified_backend(unified_db: Path) -> None:
    del unified_db
    api.mase2_upsert_fact("finance_budget", "budget", "800")
    api.mase2_upsert_fact("finance_budget", "budget", "1200")

    bn = BenchmarkNotetaker()
    results = bn.search(["budget"], full_query="what is my current budget?", limit=3)

    assert results
    assert results[0]["_source"] == "entity_state"
    assert "1200" in results[0]["content"]
    assert "800" not in results[0]["content"]


def test_correction_updates_unified_recall_result(unified_db: Path) -> None:
    del unified_db
    api.mase2_write_interaction("t1", "user", "My favorite city is Paris")
    api.mase2_upsert_fact("user_preferences", "city", "Paris")

    correction = api.mase2_correct_and_log(
        "t1",
        "Actually, my favorite city is Tokyo, not Paris",
    )
    api.mase2_upsert_fact(
        "user_preferences",
        "city",
        "Tokyo",
        reason="user_correction",
        source_log_id=correction["new_log_id"],
    )

    bn = BenchmarkNotetaker()
    results = bn.search(["city"], full_query="what is my favorite city now?", limit=3)

    assert correction["is_correction"] is True
    assert correction["superseded_count"] >= 1
    assert results[0]["_source"] == "entity_state"
    assert "Tokyo" in results[0]["content"]
    assert "Paris" not in results[0]["content"]


def test_current_state_question_prefers_fact_over_old_chat_noise(unified_db: Path) -> None:
    del unified_db
    bn = BenchmarkNotetaker()
    bn.write(
        user_query="I used to live in Shanghai, and that old city is still in my notes.",
        assistant_response="Got it, your old city note is Shanghai.",
        summary="old city note",
        thread_id="t-noise",
    )
    api.mase2_upsert_fact("location_events", "city", "Hangzhou")

    results = bn.search(
        ["__FULL_QUERY__"],
        full_query="What city do I live in now?",
        limit=3,
    )
    fact_sheet = bn.build_fact_sheet(results[:1])

    assert results
    assert results[0]["_source"] == "entity_state"
    assert "Hangzhou" in results[0]["content"]
    assert "Shanghai" not in fact_sheet
    assert "Hangzhou" in fact_sheet


def test_thread_context_tolerates_missing_topic_tokens_on_fact_results() -> None:
    ctx = derive_thread_context(
        "之前说的服务器端口是多少？",
        route_keywords=["服务器端口"],
        search_results=[
            {
                "thread_id": "fact::service-config",
                "thread_label": "服务配置",
                "topic_tokens": None,
            }
        ],
    )

    assert ctx.thread_id == "fact::service-config"
    assert ctx.topic_tokens == []


def test_thread_context_parses_json_topic_tokens_string() -> None:
    ctx = derive_thread_context(
        "再确认一下服务器端口",
        route_keywords=["服务器端口"],
        search_results=[
            {
                "thread_id": "thread-json",
                "thread_label": "服务配置",
                "topic_tokens": "[\"服务器端口\", \"服务配置\"]",
            }
        ],
    )

    assert ctx.thread_id == "thread-json"
    assert "服务器端口" in ctx.topic_tokens
