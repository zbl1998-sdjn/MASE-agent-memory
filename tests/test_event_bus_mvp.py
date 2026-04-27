from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

from event_bus import (
    EVENT_BUS_SCHEMA_VERSION,
    build_event_bus_snapshot,
    build_events_from_fact_card,
    load_event_bus_snapshot,
    query_event_bus,
)
from executor import ExecutorAgent
from legacy_archive import legacy as legacy_tools
from mase_tools import legacy as tools
from memory_reflection import build_fact_card
from notetaker_agent import NotetakerAgent


def _build_sample_fact_card(
    *,
    timestamp: str,
    month: str,
    source: str,
    thread_id: str = "thread-1",
) -> dict:
    return build_fact_card(
        {
            "timestamp": timestamp,
            "user_query": source,
            "assistant_response": "",
            "semantic_summary": source,
            "language": "en",
            "key_entities": ["tennis racket", "Downtown Sports"],
            "memory_profile": {
                "entity_cards": [{"name": "tennis racket"}],
                "event_cards": [
                    {
                        "event_type": "shopping",
                        "display_name": "new tennis racket",
                        "normalized_name": "new tennis racket",
                        "source": f"I bought a new tennis racket from Downtown Sports in {month}.",
                        "attributes": {"store": "Downtown Sports", "month": month},
                    }
                ],
            },
            "thread_id": thread_id,
            "thread_label": "tennis purchase",
        },
        f"memory\\2024-05-01\\{timestamp.replace(':', '-').replace('T', '_')}.json",
    )


def test_build_events_from_fact_card_preserves_event_card_attributes() -> None:
    fact_card = _build_sample_fact_card(
        timestamp="2024-05-01T10:00:00",
        month="May",
        source="I bought a new tennis racket from Downtown Sports in May.",
    )

    events = build_events_from_fact_card(fact_card)

    assert events
    shopping_event = next(event for event in events if event["provenance"] == "event_card")
    assert shopping_event["schema_version"] == 1
    assert shopping_event["attributes"]["store"] == "Downtown Sports"
    assert shopping_event["normalized_name"] == "new tennis racket"
    assert shopping_event["dedupe_key"]
    assert shopping_event["logical_event_id"]


def test_build_event_bus_snapshot_keeps_distinct_scoped_events_active() -> None:
    may_card = _build_sample_fact_card(
        timestamp="2024-05-01T10:00:00",
        month="May",
        source="I bought a new tennis racket from Downtown Sports in May.",
    )
    june_card = _build_sample_fact_card(
        timestamp="2024-06-15T11:00:00",
        month="June",
        source="I bought a new tennis racket from Downtown Sports in June.",
    )

    snapshot = build_event_bus_snapshot([may_card, june_card])

    active_events = [event for event in snapshot["events"] if event["status"] == "active" and event["provenance"] == "event_card"]
    assert snapshot["schema_version"] == EVENT_BUS_SCHEMA_VERSION
    assert snapshot["active_event_count"] >= 2
    assert len(active_events) >= 2
    assert {event["scope_hints"]["months"][0].lower() for event in active_events[:2]} == {"may", "june"}


def test_load_and_query_event_bus_normalizes_legacy_snapshot() -> None:
    artifacts_dir = Path(__file__).resolve().parent / "event_bus_test_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = artifacts_dir / "legacy-event-bus.json"
    try:
        snapshot_path.write_text(
            json.dumps(
                {
                    "generated_at": "2024-05-01T10:00:00",
                    "events": [
                        {
                            "event_type": "shopping",
                            "display_name": "New Tennis Racket",
                            "source": "I bought a new tennis racket from Downtown Sports in May.",
                            "entities": ["tennis racket"],
                            "scope_hints": {"months": ["may"], "locations": ["Downtown Sports"]},
                            "record_path": "memory\\2024-05-01\\10-00-00.json",
                            "timestamp": "2024-05-01T10:00:00",
                            "provenance": "event_card",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        snapshot = load_event_bus_snapshot(snapshot_path)
        results = query_event_bus(
            snapshot,
            entities=["tennis racket"],
            event_types=["shopping"],
            months=["may"],
            locations=["downtown sports"],
            active_only=True,
            limit=5,
        )

        assert snapshot["schema_version"] == EVENT_BUS_SCHEMA_VERSION
        assert snapshot["event_count"] == 1
        assert snapshot["active_event_count"] == 1
        assert results
        assert results[0]["status"] == "active"
        assert results[0]["normalized_name"] == "new tennis racket"
    finally:
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)


def test_notetaker_query_event_bus_returns_summary_and_results(monkeypatch) -> None:
    base_dir = Path(__file__).resolve().parent / "event_bus_test_artifacts"
    system_dir = base_dir / "system"
    system_dir.mkdir(parents=True, exist_ok=True)
    try:
        snapshot = build_event_bus_snapshot(
            [
                _build_sample_fact_card(
                    timestamp="2024-05-01T10:00:00",
                    month="May",
                    source="I bought a new tennis racket from Downtown Sports in May.",
                )
            ]
        )
        (system_dir / "event-bus-latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr("notetaker_agent.get_memory_dir", lambda: base_dir)
        agent = NotetakerAgent(model_interface=None)
        query_result = agent.query_event_bus(
            entities=["tennis racket"],
            event_types=["shopping"],
            months=["may"],
            active_only=True,
            limit=3,
        )

        assert query_result["snapshot_summary"]["event_count"] == snapshot["event_count"]
        assert query_result["filters"]["limit"] == 3
        assert query_result["results"]
        assert query_result["results"][0]["event_type"] == "shopping"
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_search_memory_uses_event_bus_for_state_transition_queries(monkeypatch) -> None:
    base_dir = Path(__file__).resolve().parent / "event_bus_test_artifacts"
    system_dir = base_dir / "system"
    date_dir = base_dir / "2024-05-01"
    system_dir.mkdir(parents=True, exist_ok=True)
    date_dir.mkdir(parents=True, exist_ok=True)
    try:
        previous_record_path = date_dir / "09-00-00.json"
        current_record_path = date_dir / "11-00-00.json"
        previous_record = {
            "timestamp": "2024-05-01T09:00:00",
            "user_query": "The initial quote for the trip was $120.",
            "assistant_response": "",
            "semantic_summary": "Initial quote for the trip was $120.",
            "memory_profile": {},
            "metadata": {},
        }
        current_record = {
            "timestamp": "2024-05-01T11:00:00",
            "user_query": "The final quote for the trip was $90.",
            "assistant_response": "",
            "semantic_summary": "Final quote for the trip was $90.",
            "memory_profile": {},
            "metadata": {},
        }
        previous_record_path.write_text(json.dumps(previous_record, ensure_ascii=False, indent=2), encoding="utf-8")
        current_record_path.write_text(json.dumps(current_record, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshot = build_event_bus_snapshot(
            [
                {
                    "events": [
                        {
                            "event_id": "quote-v1",
                            "logical_event_id": "price_quote|trip quote",
                            "event_type": "price_quote",
                            "display_name": "trip quote",
                            "normalized_name": "trip quote",
                            "timestamp": "2024-05-01T09:00:00",
                            "entities": ["trip", "quote"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": []},
                            "source": "The initial quote for the trip was $120.",
                            "polarity": "positive",
                            "attributes": {"amount": 120},
                            "record_path": str(previous_record_path),
                            "thread_id": "thread-1",
                            "thread_label": "trip pricing",
                            "provenance": "test",
                        },
                        {
                            "event_id": "quote-v2",
                            "logical_event_id": "price_quote|trip quote",
                            "event_type": "price_quote",
                            "display_name": "trip quote",
                            "normalized_name": "trip quote",
                            "timestamp": "2024-05-01T11:00:00",
                            "entities": ["trip", "quote"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": []},
                            "source": "The final quote for the trip was $90.",
                            "polarity": "positive",
                            "attributes": {"amount": 90},
                            "record_path": str(current_record_path),
                            "thread_id": "thread-1",
                            "thread_label": "trip pricing",
                            "provenance": "test",
                        },
                    ]
                }
            ]
        )
        (system_dir / "event-bus-latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr(tools, "ensure_memory_dir", lambda: base_dir)
        monkeypatch.setattr(tools, "_search_english_memory", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "search_fact_cards", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "semantic_search_memory", lambda *args, **kwargs: [])

        results = tools.search_memory(
            keywords=["trip", "quote"],
            full_query="How much more did I have to pay for the trip after the initial quote?",
            semantic_query="How much more did I have to pay for the trip after the initial quote?",
            limit=5,
        )

        assert len(results) == 2
        assert {item.get("event_bus_view_role") for item in results} == {"current", "previous"}
        assert {Path(str(item["filepath"])).name for item in results} == {"09-00-00.json", "11-00-00.json"}
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_search_memory_uses_event_bus_for_current_state_queries(monkeypatch) -> None:
    base_dir = Path(__file__).resolve().parent / "event_bus_test_artifacts_current"
    system_dir = base_dir / "system"
    date_dir = base_dir / "2024-05-02"
    system_dir.mkdir(parents=True, exist_ok=True)
    date_dir.mkdir(parents=True, exist_ok=True)
    try:
        road_bike_path = date_dir / "09-00-00.json"
        mountain_bike_path = date_dir / "10-00-00.json"
        road_bike_record = {
            "timestamp": "2024-05-02T09:00:00",
            "user_query": "I currently own a road bike.",
            "assistant_response": "",
            "semantic_summary": "I currently own a road bike.",
            "memory_profile": {},
            "metadata": {},
        }
        mountain_bike_record = {
            "timestamp": "2024-05-02T10:00:00",
            "user_query": "I currently own a mountain bike.",
            "assistant_response": "",
            "semantic_summary": "I currently own a mountain bike.",
            "memory_profile": {},
            "metadata": {},
        }
        road_bike_path.write_text(json.dumps(road_bike_record, ensure_ascii=False, indent=2), encoding="utf-8")
        mountain_bike_path.write_text(json.dumps(mountain_bike_record, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshot = build_event_bus_snapshot(
            [
                {
                    "events": [
                        {
                            "event_id": "bike-road",
                            "logical_event_id": "bike_ownership|bike|road bike",
                            "event_type": "bike_ownership",
                            "display_name": "road bike",
                            "normalized_name": "road bike",
                            "timestamp": "2024-05-02T09:00:00",
                            "entities": ["bike", "road bike"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": []},
                            "source": "I currently own a road bike.",
                            "polarity": "positive",
                            "attributes": {"count": 1},
                            "record_path": str(road_bike_path),
                            "thread_id": "thread-bike",
                            "thread_label": "bike inventory",
                            "provenance": "test",
                        },
                        {
                            "event_id": "bike-mountain",
                            "logical_event_id": "bike_ownership|bike|mountain bike",
                            "event_type": "bike_ownership",
                            "display_name": "mountain bike",
                            "normalized_name": "mountain bike",
                            "timestamp": "2024-05-02T10:00:00",
                            "entities": ["bike", "mountain bike"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": []},
                            "source": "I currently own a mountain bike.",
                            "polarity": "positive",
                            "attributes": {"count": 1},
                            "record_path": str(mountain_bike_path),
                            "thread_id": "thread-bike",
                            "thread_label": "bike inventory",
                            "provenance": "test",
                        },
                    ]
                }
            ]
        )
        (system_dir / "event-bus-latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr(tools, "ensure_memory_dir", lambda: base_dir)
        monkeypatch.setattr(tools, "_search_english_memory", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "search_fact_cards", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "semantic_search_memory", lambda *args, **kwargs: [])

        results = tools.search_memory(
            keywords=["bike"],
            full_query="How many bikes do I currently own?",
            semantic_query="How many bikes do I currently own?",
            limit=5,
        )

        assert len(results) == 2
        assert {item.get("event_bus_view_role") for item in results} == {"current"}
        assert {Path(str(item["filepath"])).name for item in results} == {"09-00-00.json", "10-00-00.json"}
        notes = tools._extract_current_count_reasoning_from_results("How many bikes do I currently own?", results)
        assert any("Deterministic item count: 2" in note for note in notes)
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_search_memory_uses_event_bus_for_latest_relocation_queries(monkeypatch) -> None:
    base_dir = Path(__file__).resolve().parent / "event_bus_test_artifacts_latest"
    system_dir = base_dir / "system"
    date_dir = base_dir / "2024-05-03"
    system_dir.mkdir(parents=True, exist_ok=True)
    date_dir.mkdir(parents=True, exist_ok=True)
    try:
        old_path = date_dir / "09-00-00.json"
        current_path = date_dir / "18-00-00.json"
        old_record = {
            "timestamp": "2024-05-03T09:00:00",
            "user_query": "Rachel used to live in Austin.",
            "assistant_response": "",
            "semantic_summary": "Rachel used to live in Austin.",
            "memory_profile": {},
            "metadata": {},
        }
        current_record = {
            "timestamp": "2024-05-03T18:00:00",
            "user_query": "Rachel moved to Denver after her recent relocation.",
            "assistant_response": "",
            "semantic_summary": "Rachel moved to Denver after her recent relocation.",
            "memory_profile": {},
            "metadata": {},
        }
        old_path.write_text(json.dumps(old_record, ensure_ascii=False, indent=2), encoding="utf-8")
        current_path.write_text(json.dumps(current_record, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshot = build_event_bus_snapshot(
            [
                {
                    "events": [
                        {
                            "event_id": "home-v1",
                            "logical_event_id": "residence|rachel home",
                            "event_type": "residence",
                            "display_name": "Rachel home",
                            "normalized_name": "rachel home",
                            "timestamp": "2024-05-03T09:00:00",
                            "entities": ["Rachel", "Austin"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": ["Austin"]},
                            "source": "Rachel used to live in Austin.",
                            "polarity": "positive",
                            "attributes": {"location": "Austin"},
                            "record_path": str(old_path),
                            "thread_id": "thread-rachel",
                            "thread_label": "relocation",
                            "provenance": "test",
                        },
                        {
                            "event_id": "home-v2",
                            "logical_event_id": "residence|rachel home",
                            "event_type": "residence",
                            "display_name": "Rachel home",
                            "normalized_name": "rachel home",
                            "timestamp": "2024-05-03T18:00:00",
                            "entities": ["Rachel", "Denver"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": ["Denver"]},
                            "source": "Rachel moved to Denver after her recent relocation.",
                            "polarity": "positive",
                            "attributes": {"location": "Denver"},
                            "record_path": str(current_path),
                            "thread_id": "thread-rachel",
                            "thread_label": "relocation",
                            "provenance": "test",
                        },
                    ]
                }
            ]
        )
        (system_dir / "event-bus-latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr(tools, "ensure_memory_dir", lambda: base_dir)
        monkeypatch.setattr(tools, "_search_english_memory", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "search_fact_cards", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "semantic_search_memory", lambda *args, **kwargs: [])

        results = tools.search_memory(
            keywords=["Rachel", "relocation"],
            full_query="Where did Rachel move to after her recent relocation?",
            semantic_query="Where did Rachel move to after her recent relocation?",
            limit=5,
        )

        assert len(results) == 1
        assert results[0].get("event_bus_view_role") == "current"
        assert Path(str(results[0]["filepath"])).name == "18-00-00.json"
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_search_memory_prefers_event_bus_current_result_across_backend_merges(monkeypatch) -> None:
    legacy_old_result = {
        "date": "2024-05-03",
        "time": "09-00-00",
        "summary": "Rachel used to live in Austin.",
        "user_query": "Rachel used to live in Austin.",
        "assistant_response": "",
        "timestamp": "2024-05-03T09:00:00",
        "language": "en",
        "key_entities": ["Rachel", "Austin"],
        "filepath": "memory\\2024-05-03\\09-00-00.json",
        "thread_id": "thread-rachel",
        "thread_label": "relocation",
        "topic_tokens": ["Rachel", "relocation"],
        "memory_profile": {},
        "scope_hints": {},
        "metadata": {},
        "_priority": 10,
        "_index": 0,
    }
    current_event_bus_result = {
        "date": "2024-05-03",
        "time": "18-00-00",
        "summary": "Rachel moved to Denver after her recent relocation.",
        "user_query": "Rachel moved to Denver after her recent relocation.",
        "assistant_response": "",
        "timestamp": "2024-05-03T18:00:00",
        "language": "en",
        "key_entities": ["Rachel", "Denver"],
        "filepath": "memory\\2024-05-03\\18-00-00.json",
        "thread_id": "thread-rachel",
        "thread_label": "relocation",
        "topic_tokens": ["Rachel", "relocation"],
        "memory_profile": {},
        "scope_hints": {},
        "metadata": {},
        "_priority": 100,
        "_index": 1,
        "event_bus_view_role": "current",
        "event_bus_match": {
            "event_id": "home-merge-v2",
            "logical_event_id": "residence|rachel home",
            "event_type": "residence",
            "status": "active",
            "source": "Rachel moved to Denver after her recent relocation.",
            "timestamp": "2024-05-03T18:00:00",
            "entities": ["Rachel", "Denver"],
            "attributes": {"location": "Denver"},
        },
    }

    monkeypatch.setattr(legacy_tools, "_search_english_memory", lambda *args, **kwargs: [dict(legacy_old_result)])
    monkeypatch.setattr(
        legacy_tools,
        "search_fact_cards",
        lambda *args, **kwargs: [dict(legacy_old_result, fact_card={"event_type": "residence"})],
    )
    monkeypatch.setattr(
        legacy_tools,
        "_search_event_bus_for_state_queries",
        lambda **kwargs: [dict(current_event_bus_result)],
    )
    monkeypatch.setattr(legacy_tools, "semantic_search_memory", lambda *args, **kwargs: [])

    results = tools.search_memory(
        keywords=["Rachel", "relocation"],
        full_query="Where did Rachel move to after her recent relocation?",
        semantic_query="Where did Rachel move to after her recent relocation?",
        limit=5,
    )

    assert results[0].get("event_bus_view_role") == "current"
    assert "Denver" in str(results[0].get("summary") or results[0].get("user_query") or "")
    assert "Denver" in str(results[0].get("event_bus_match", {}).get("source") or "")


def test_search_memory_uses_event_bus_for_personal_best_queries(monkeypatch) -> None:
    base_dir = Path(__file__).resolve().parent / "event_bus_test_artifacts_best"
    system_dir = base_dir / "system"
    date_dir = base_dir / "2024-05-04"
    system_dir.mkdir(parents=True, exist_ok=True)
    date_dir.mkdir(parents=True, exist_ok=True)
    try:
        earlier_path = date_dir / "08-00-00.json"
        best_path = date_dir / "17-00-00.json"
        earlier_record = {
            "timestamp": "2024-05-04T08:00:00",
            "user_query": "My charity 5K time was 26:40.",
            "assistant_response": "",
            "semantic_summary": "My charity 5K time was 26:40.",
            "memory_profile": {},
            "metadata": {},
        }
        best_record = {
            "timestamp": "2024-05-04T17:00:00",
            "user_query": "I set a new personal best of 24:55 in the charity 5K run.",
            "assistant_response": "",
            "semantic_summary": "I set a new personal best of 24:55 in the charity 5K run.",
            "memory_profile": {},
            "metadata": {},
        }
        earlier_path.write_text(json.dumps(earlier_record, ensure_ascii=False, indent=2), encoding="utf-8")
        best_path.write_text(json.dumps(best_record, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshot = build_event_bus_snapshot(
            [
                {
                    "events": [
                        {
                            "event_id": "run-v1",
                            "logical_event_id": "race_result|charity 5k",
                            "event_type": "race_result",
                            "display_name": "charity 5K",
                            "normalized_name": "charity 5k",
                            "timestamp": "2024-05-04T08:00:00",
                            "entities": ["charity 5K"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": []},
                            "source": "My charity 5K time was 26:40.",
                            "polarity": "positive",
                            "attributes": {"time": "26:40"},
                            "record_path": str(earlier_path),
                            "thread_id": "thread-run",
                            "thread_label": "race progress",
                            "provenance": "test",
                        },
                        {
                            "event_id": "run-v2",
                            "logical_event_id": "race_result|charity 5k",
                            "event_type": "race_result",
                            "display_name": "charity 5K",
                            "normalized_name": "charity 5k",
                            "timestamp": "2024-05-04T17:00:00",
                            "entities": ["charity 5K"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": []},
                            "source": "I set a new personal best of 24:55 in the charity 5K run.",
                            "polarity": "positive",
                            "attributes": {"time": "24:55", "personal_best": True},
                            "record_path": str(best_path),
                            "thread_id": "thread-run",
                            "thread_label": "race progress",
                            "provenance": "test",
                        },
                    ]
                }
            ]
        )
        (system_dir / "event-bus-latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr(tools, "ensure_memory_dir", lambda: base_dir)
        monkeypatch.setattr(tools, "_search_english_memory", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "search_fact_cards", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "semantic_search_memory", lambda *args, **kwargs: [])

        results = tools.search_memory(
            keywords=["charity", "5K"],
            full_query="What was my personal best time in the charity 5K run?",
            semantic_query="What was my personal best time in the charity 5K run?",
            limit=5,
        )

        assert len(results) == 1
        assert results[0].get("event_bus_view_role") == "current"
        assert Path(str(results[0]["filepath"])).name == "17-00-00.json"
        candidate_lines = tools._event_bus_candidate_lines("What was my personal best time in the charity 5K run?", results)
        assert candidate_lines and "24:55" in candidate_lines[0]
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_search_memory_event_bus_skips_question_echo_generic_records(monkeypatch) -> None:
    base_dir = Path(__file__).resolve().parent / "event_bus_test_artifacts_query_echo"
    system_dir = base_dir / "system"
    date_dir = base_dir / "2024-05-07"
    system_dir.mkdir(parents=True, exist_ok=True)
    date_dir.mkdir(parents=True, exist_ok=True)
    try:
        old_path = date_dir / "09-00-00.json"
        current_path = date_dir / "18-00-00.json"
        query_path = base_dir / "2026-04-14" / "11-00-00.json"
        query_path.parent.mkdir(parents=True, exist_ok=True)

        old_record = {
            "timestamp": "2024-05-07T09:00:00",
            "user_query": "Rachel used to live in Austin.",
            "assistant_response": "",
            "semantic_summary": "Rachel used to live in Austin.",
            "memory_profile": {},
            "metadata": {},
        }
        current_record = {
            "timestamp": "2024-05-07T18:00:00",
            "user_query": "Rachel moved back to the suburbs after her recent relocation.",
            "assistant_response": "",
            "semantic_summary": "Rachel moved back to the suburbs after her recent relocation.",
            "memory_profile": {},
            "metadata": {},
        }
        query_record = {
            "timestamp": "2026-04-14T11:00:00",
            "user_query": "Where did Rachel move to after her recent relocation?",
            "assistant_response": "",
            "semantic_summary": "Where did Rachel move to after her recent relocation?",
            "memory_profile": {},
            "metadata": {},
        }
        old_path.write_text(json.dumps(old_record, ensure_ascii=False, indent=2), encoding="utf-8")
        current_path.write_text(json.dumps(current_record, ensure_ascii=False, indent=2), encoding="utf-8")
        query_path.write_text(json.dumps(query_record, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshot = build_event_bus_snapshot(
            [
                {
                    "events": [
                        {
                            "event_id": "home-v1",
                            "logical_event_id": "residence|rachel home",
                            "event_type": "residence",
                            "display_name": "Rachel home",
                            "normalized_name": "rachel home",
                            "timestamp": "2024-05-07T09:00:00",
                            "entities": ["Rachel", "Austin"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": ["Austin"]},
                            "source": "Rachel used to live in Austin.",
                            "polarity": "positive",
                            "attributes": {"location": "Austin"},
                            "record_path": str(old_path),
                            "thread_id": "thread-rachel",
                            "thread_label": "relocation",
                            "provenance": "test",
                        },
                        {
                            "event_id": "home-v2",
                            "logical_event_id": "residence|rachel home",
                            "event_type": "residence",
                            "display_name": "Rachel home",
                            "normalized_name": "rachel home",
                            "timestamp": "2024-05-07T18:00:00",
                            "entities": ["Rachel", "suburbs"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": ["suburbs"]},
                            "source": "Rachel moved back to the suburbs after her recent relocation.",
                            "polarity": "positive",
                            "attributes": {"location": "suburbs"},
                            "record_path": str(current_path),
                            "thread_id": "thread-rachel",
                            "thread_label": "relocation",
                            "provenance": "test",
                        },
                        {
                            "event_id": "query-echo",
                            "logical_event_id": "generic|rachel",
                            "event_type": "generic",
                            "display_name": "Rachel relocation question",
                            "normalized_name": "rachel relocation question",
                            "timestamp": "2026-04-14T11:00:00",
                            "entities": ["Rachel"],
                            "scope_hints": {"months": ["april"], "weekdays": [], "locations": []},
                            "source": "Where did Rachel move to after her recent relocation?",
                            "polarity": "positive",
                            "attributes": {},
                            "record_path": str(query_path),
                            "thread_id": "thread-query",
                            "thread_label": "question echo",
                            "provenance": "test",
                        },
                    ]
                }
            ]
        )
        (system_dir / "event-bus-latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr(tools, "ensure_memory_dir", lambda: base_dir)
        monkeypatch.setattr(tools, "_search_english_memory", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "search_fact_cards", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "semantic_search_memory", lambda *args, **kwargs: [])

        results = tools.search_memory(
            keywords=["Rachel", "relocation"],
            full_query="Where did Rachel move to after her recent relocation?",
            semantic_query="Where did Rachel move to after her recent relocation?",
            limit=5,
        )

        assert results
        assert Path(str(results[0]["filepath"])).name == "18-00-00.json"
        assert all("11-00-00.json" not in str(item.get("filepath")) for item in results)
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_search_memory_preserves_event_bus_metadata_when_base_result_exists(monkeypatch) -> None:
    base_dir = Path(__file__).resolve().parent / "event_bus_test_artifacts_merge"
    system_dir = base_dir / "system"
    date_dir = base_dir / "2024-05-06"
    system_dir.mkdir(parents=True, exist_ok=True)
    date_dir.mkdir(parents=True, exist_ok=True)
    try:
        current_path = date_dir / "12-00-00.json"
        current_record = {
            "timestamp": "2024-05-06T12:00:00",
            "user_query": "The final quote for the trip was $90.",
            "assistant_response": "",
            "semantic_summary": "Final quote for the trip was $90.",
            "memory_profile": {},
            "metadata": {},
        }
        current_path.write_text(json.dumps(current_record, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshot = build_event_bus_snapshot(
            [
                {
                    "events": [
                        {
                            "event_id": "quote-final",
                            "logical_event_id": "price_quote|trip quote",
                            "event_type": "price_quote",
                            "display_name": "trip quote",
                            "normalized_name": "trip quote",
                            "timestamp": "2024-05-06T12:00:00",
                            "entities": ["trip", "quote"],
                            "scope_hints": {"months": ["may"], "weekdays": [], "locations": []},
                            "source": "The final quote for the trip was $90.",
                            "polarity": "positive",
                            "attributes": {"amount": 90},
                            "record_path": str(current_path),
                            "thread_id": "thread-quote",
                            "thread_label": "trip pricing",
                            "provenance": "test",
                        }
                    ]
                }
            ]
        )
        (system_dir / "event-bus-latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr(tools, "ensure_memory_dir", lambda: base_dir)
        monkeypatch.setattr(
            tools,
            "_search_english_memory",
            lambda *args, **kwargs: [
                {
                    "date": "2024-05-06",
                    "time": "12-00-00",
                    "summary": current_record["semantic_summary"],
                    "user_query": current_record["user_query"],
                    "assistant_response": "",
                    "timestamp": current_record["timestamp"],
                    "language": "en",
                    "key_entities": ["trip", "quote"],
                    "filepath": str(current_path),
                    "thread_id": "thread-quote",
                    "thread_label": "trip pricing",
                    "topic_tokens": ["trip", "quote"],
                    "memory_profile": {},
                    "scope_hints": {},
                    "metadata": {},
                    "_priority": 999,
                    "_index": 0,
                }
            ],
        )
        monkeypatch.setattr(tools, "search_fact_cards", lambda *args, **kwargs: [])
        monkeypatch.setattr(tools, "semantic_search_memory", lambda *args, **kwargs: [])

        results = tools.search_memory(
            keywords=["trip", "quote"],
            full_query="What was the final quote for the trip?",
            semantic_query="What was the final quote for the trip?",
            limit=5,
        )

        assert len(results) == 1
        assert results[0].get("event_bus_view_role") == "current"
        assert results[0].get("event_bus_match", {}).get("logical_event_id") == "price_quote|trip quote"
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_latest_money_reasoning_prefers_newer_preapproval_amount() -> None:
    results = [
        {
            "timestamp": "2024-02-10T09:00:00",
            "user_query": "Wells Fargo initially pre-approved me for $350,000 on my mortgage.",
            "summary": "Wells Fargo initially pre-approved me for $350,000 on my mortgage.",
            "assistant_response": "",
        },
        {
            "timestamp": "2024-03-15T18:30:00",
            "user_query": "Wells Fargo later increased my mortgage pre-approval to $400,000.",
            "summary": "Wells Fargo later increased my mortgage pre-approval to $400,000.",
            "assistant_response": "",
        },
    ]

    notes = tools._extract_latest_state_value_reasoning_from_results(
        "What was the amount I was pre-approved for when I got my mortgage from Wells Fargo?",
        results,
    )

    assert any("Deterministic money value: latest = $400,000" in note for note in notes)


def test_state_transition_reasoning_from_results_uses_newer_snapshot() -> None:
    results = [
        {
            "timestamp": "2024-01-04T10:00:00",
            "user_query": "When I just started my new role as Senior Software Engineer, I led 4 engineers.",
            "summary": "When I just started my new role as Senior Software Engineer, I led 4 engineers.",
            "assistant_response": "",
        },
        {
            "timestamp": "2024-06-20T09:00:00",
            "user_query": "In my Senior Software Engineer role, I now lead 5 engineers.",
            "summary": "In my Senior Software Engineer role, I now lead 5 engineers.",
            "assistant_response": "",
        },
    ]

    notes = tools._extract_state_transition_reasoning_from_results(
        "How many engineers do I lead when I just started my new role as Senior Software Engineer? How many engineers do I lead now?",
        results,
    )

    assert any("previous = 4 engineers ; current = 5 engineers" in note for note in notes)


def test_state_transition_reasoning_skips_current_only_questions() -> None:
    results = [
        {
            "timestamp": "2024-01-04T10:00:00",
            "user_query": "I used to own 3 bikes.",
            "summary": "I used to own 3 bikes.",
            "assistant_response": "",
        },
        {
            "timestamp": "2024-06-20T09:00:00",
            "user_query": "I now own 4 bikes.",
            "summary": "I now own 4 bikes.",
            "assistant_response": "",
        },
    ]

    notes = tools._extract_state_transition_reasoning_from_results(
        "How many bikes do I currently own?",
        results,
    )

    assert notes == []


def test_build_aggregation_notes_prefers_current_count_over_transition_fallback_for_current_only_query() -> None:
    results = [
        {
            "timestamp": "2023-05-22T03:27:00",
            "user_query": "I've got 25 titles on my to-watch list right now, and it's getting a bit hard to keep track of.",
            "summary": "I've got 25 titles on my to-watch list right now.",
            "assistant_response": "",
        },
        {
            "timestamp": "2023-05-20T10:19:00",
            "user_query": "I've got a pretty long to-watch list right now, with 20 titles waiting to be checked off.",
            "summary": "I've got 20 titles on my to-watch list.",
            "assistant_response": "",
        },
    ]

    notes = tools._build_aggregation_notes("How many titles are currently on my to-watch list?", results)

    assert any("Deterministic item count: 25" in note for note in notes)
    assert not any("Deterministic state transition" in note for note in notes)


def test_latest_count_reasoning_prefers_newer_cumulative_update() -> None:
    results = [
        {
            "timestamp": "2023-08-15T09:00:00",
            "user_query": "I've tried three different Korean restaurants recently.",
            "summary": "I've tried three different Korean restaurants recently.",
            "assistant_response": "",
        },
        {
            "timestamp": "2023-09-30T18:00:00",
            "user_query": "Have you tried any good Korean restaurants in my city lately? I've tried four different ones so far.",
            "summary": "I've tried four different Korean restaurants so far.",
            "assistant_response": "",
        },
    ]

    notes = tools._extract_latest_count_reasoning_from_results(
        "How many Korean restaurants have I tried in my city?",
        results,
    )

    assert any("Deterministic item count: 4" in note for note in notes)


def test_latest_count_reasoning_prefers_benchmark_sequence_over_same_day_timestamp() -> None:
    results = [
        {
            "timestamp": "2023-05-30T22:16:00",
            "user_query": "I've worn my new black Converse Chuck Taylor All Star sneakers four times already.",
            "summary": "I've worn my new black Converse Chuck Taylor All Star sneakers four times already.",
            "assistant_response": "",
            "metadata": {"benchmark_turn_index": 4},
        },
        {
            "timestamp": "2023-05-30T17:45:00",
            "user_query": "That's six times now that I've worn my new black Converse Chuck Taylor All Star sneakers.",
            "summary": "That's six times now that I've worn my new black Converse Chuck Taylor All Star sneakers.",
            "assistant_response": "",
            "metadata": {"benchmark_turn_index": 7},
        },
    ]

    notes = tools._extract_latest_count_reasoning_from_results(
        "How many times have I worn my new black Converse Chuck Taylor All Star sneakers?",
        results,
    )

    assert any("Deterministic item count: 6" in note for note in notes)


def test_latest_count_reasoning_uses_newer_record_timestamp_for_retrospective_update() -> None:
    results = [
        {
            "timestamp": "2023-05-11T02:24:00",
            "user_query": "I did attend three sessions of the bereavement support group, and it really helped me process my emotions.",
            "summary": "I did attend three sessions of the bereavement support group.",
            "assistant_response": "",
        },
        {
            "timestamp": "2023-10-30T07:19:00",
            "user_query": "By the way, I was thinking about the bereavement support group I attended last year. I remember attending five sessions and finding it really helpful in processing my emotions.",
            "summary": "I remember attending five sessions of the bereavement support group.",
            "assistant_response": "",
        },
    ]

    notes = tools._extract_latest_count_reasoning_from_results(
        "How many sessions of the bereavement support group did I attend?",
        results,
    )

    assert any("Deterministic item count: 5" in note for note in notes)


def test_latest_quantity_reasoning_prefers_latest_progress_estimate() -> None:
    results = [
        {
            "timestamp": "2023-06-11T03:51:00",
            "user_query": "I've been working on an abstract ocean sculpture at home, and I've spent around 5-6 hours on it so far.",
            "summary": "I've spent around 5-6 hours on my abstract ocean sculpture so far.",
            "assistant_response": "",
        },
        {
            "timestamp": "2023-06-17T09:26:00",
            "user_query": "I've already spent 10-12 hours on my abstract ocean sculpture, and I'm excited to explore new techniques and materials for my next piece.",
            "summary": "I've already spent 10-12 hours on my abstract ocean sculpture.",
            "assistant_response": "",
        },
    ]

    notes = tools._extract_latest_quantity_reasoning_from_results(
        "How many hours have I spent on my abstract ocean sculpture?",
        results,
    )

    assert any("Deterministic scalar value: 10-12 hours" in note for note in notes)


def test_text_state_transition_reasoning_extracts_airline_status_update() -> None:
    results = [
        {
            "timestamp": "2022-09-16T17:22:00",
            "user_query": "I just hit 20,000 miles on United Airlines, which means I'm finally eligible for Premier Silver status.",
            "summary": "I reached Premier Silver status on United Airlines.",
            "assistant_response": "",
            "metadata": {"benchmark_turn_index": 3},
        },
        {
            "timestamp": "2023-05-30T08:58:00",
            "user_query": "I do have a United Airlines MileagePlus account - I just reached Premier Gold status.",
            "summary": "I reached Premier Gold status on United Airlines.",
            "assistant_response": "",
            "metadata": {"benchmark_turn_index": 9},
        },
    ]

    notes = tools._extract_text_state_transition_reasoning_from_results(
        "What was my previous frequent flyer status on United Airlines before I got the current status?",
        results,
    )

    assert any("previous = Premier Silver ; current = Premier Gold" in note for note in notes)


def test_text_state_transition_reasoning_extracts_frequency_update() -> None:
    results = [
        {
            "timestamp": "2023-03-11T18:01:00",
            "user_query": "I was just at the local park last Sunday, and it reminded me of my own weekly tennis sessions with friends.",
            "summary": "I played tennis with my friends every week.",
            "assistant_response": "",
            "metadata": {"benchmark_turn_index": 2},
        },
        {
            "timestamp": "2023-07-30T04:03:00",
            "user_query": "I'm planning to play tennis with my friends at the local park this Sunday, like we do every other week.",
            "summary": "I now play tennis every other week.",
            "assistant_response": "",
            "metadata": {"benchmark_turn_index": 8},
        },
    ]

    notes = tools._extract_text_state_transition_reasoning_from_results(
        "How often do I play tennis with my friends at the local park previously? How often do I play now?",
        results,
    )

    assert any("previous = every week (on Sunday) ; current = every other week (on Sunday)" in note for note in notes)


def test_build_aggregation_notes_prefers_status_transition_over_money_noise() -> None:
    results = [
        {
            "timestamp": "2022-09-16T17:22:00",
            "user_query": "I actually just hit 20,000 miles on United Airlines, which means I'm finally eligible for Premier Silver status.",
            "summary": "I reached Premier Silver status on United Airlines.",
            "assistant_response": "",
            "metadata": {"benchmark_turn_index": 3},
        },
        {
            "timestamp": "2023-05-30T08:58:00",
            "user_query": "I'm looking for Economy tickets and my budget is around $400. Oh, and I do have a United Airlines MileagePlus account - I just reached Premier Gold status.",
            "summary": "I reached Premier Gold status on United Airlines.",
            "assistant_response": "",
            "metadata": {"benchmark_turn_index": 9},
        },
    ]

    notes = tools._build_aggregation_notes(
        "What was my previous frequent flyer status on United Airlines before I got the current status?",
        results,
    )

    assert any("previous = Premier Silver ; current = Premier Gold" in note for note in notes)
    assert not any("$400" in note and "state transition" in note.lower() for note in notes)


def test_prepare_evidence_results_preserves_retrieval_order_for_current_state_queries() -> None:
    results = [
        {"timestamp": "2023-10-10T01:12:00", "summary": "Since I'll have four bikes with me, I'll make sure to book accommodations with bike storage."},
        {"timestamp": "2023-02-22T20:54:00", "summary": "By the way, I currently have three bikes, and I'm wondering if that's too many."},
        {"timestamp": "2023-10-10T01:12:00", "summary": "I'll bring all my bikes on the trip."},
    ]

    prepared = tools._prepare_evidence_results("How many bikes do I currently own?", results, max_items=2)

    assert prepared == results[:2]


def test_focus_search_results_preserves_retrieval_order_for_current_state_queries() -> None:
    results = [
        {"timestamp": "2023-10-10T01:12:00", "summary": "Since I'll have four bikes with me, I'll make sure to book accommodations with bike storage."},
        {"timestamp": "2023-02-22T20:54:00", "summary": "By the way, I currently have three bikes, and I'm wondering if that's too many."},
        {"timestamp": "2023-10-10T01:12:00", "summary": "I'll bring all my bikes on the trip."},
    ]

    focused = tools.focus_search_results(results, "How many bikes do I currently own?", max_items=2)

    assert focused == results[:2]


def test_focus_search_results_preserves_retrieval_order_for_relocation_queries() -> None:
    results = [
        {"timestamp": "2023-05-27T04:45:00", "summary": "Rachel moved back to the suburbs again."},
        {"timestamp": "2023-05-24T22:23:00", "summary": "Rachel recently moved to a new apartment in the city."},
        {"timestamp": "2023-05-24T22:23:00", "summary": "I'll ask Rachel about her neighborhood and favorite spots in the city."},
    ]

    focused = tools.focus_search_results(results, "Where did Rachel move to after her recent relocation?", max_items=2)

    assert focused == results[:2]


def test_scalar_phrase_reasoning_extracts_therapy_frequency() -> None:
    results = [
        {
            "timestamp": "2023-11-03T19:56:00",
            "user_query": "And by the way, speaking of boundaries, I see Dr. Smith every week, and she's been helping me work on this stuff.",
            "summary": "I see Dr. Smith every week.",
            "assistant_response": "",
        }
    ]

    notes = tools._extract_scalar_phrase_reasoning_from_results(
        "How often do I see my therapist, Dr. Smith?",
        results,
    )

    assert any("Deterministic scalar value: every week" in note for note in notes)


def test_scalar_phrase_reasoning_prefers_latest_relocation_location() -> None:
    results = [
        {
            "timestamp": "2023-05-24T22:23:00",
            "user_query": "Rachel recently moved to a new apartment in the city.",
            "summary": "Rachel recently moved to a new apartment in the city.",
            "assistant_response": "",
        },
        {
            "timestamp": "2023-05-27T04:45:00",
            "user_query": "My friend Rachel actually just moved back to the suburbs again.",
            "summary": "Rachel moved back to the suburbs again.",
            "assistant_response": "",
        },
    ]

    notes = tools._extract_scalar_phrase_reasoning_from_results(
        "Where did Rachel move to after her recent relocation?",
        results,
    )

    assert any("Deterministic scalar value: the suburbs" in note for note in notes)


def test_abstention_pregate_flags_role_title_mismatch() -> None:
    results = [
        {
            "timestamp": "2023-05-25T19:20:00",
            "user_query": "By the way, how many engineers do I lead in my new role as Senior Software Engineer?",
            "summary": "I lead a team of 4 engineers in my new role as Senior Software Engineer.",
            "assistant_response": "",
        }
    ]

    pre_gate = tools._assess_abstention_pregate(
        "How many engineers do I lead when I just started my new role as Software Engineer Manager?",
        results,
    )

    assert pre_gate is not None
    assert "missing_anchor" in pre_gate["reason_codes"]
    assert "competing_senior_software_engineer" in pre_gate["reason_codes"]


def test_build_fact_card_filters_meta_answer_contamination() -> None:
    fact_card = build_fact_card(
        {
            "timestamp": "2024-05-08T09:00:00",
            "user_query": "I now lead 5 engineers in my Senior Software Engineer role.",
            "assistant_response": "Based on the provided evidence, you now lead 4 engineers.",
            "semantic_summary": "I now lead 5 engineers in my Senior Software Engineer role.",
            "language": "en",
            "key_entities": ["Senior Software Engineer"],
            "memory_profile": {
                "event_cards": [
                    {
                        "event_type": "role_update",
                        "display_name": "team size recap",
                        "source": "Based on the provided evidence, you now lead 4 engineers.",
                    },
                    {
                        "event_type": "role_update",
                        "display_name": "senior software engineer team",
                        "source": "I now lead 5 engineers in my Senior Software Engineer role.",
                    },
                ]
            },
        },
        Path("memory.json"),
    )

    event_sources = [str(event.get("source") or "") for event in fact_card.get("events", [])]
    assert any("5 engineers" in source for source in event_sources)
    assert all("Based on the provided evidence" not in source for source in event_sources)


def test_executor_prefers_deterministic_scalar_value_for_personal_best() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I recently set a personal best time in a charity 5K run with a time of 27:12.
- Atomic fact: I'm hoping to beat my personal best time of 25:50 this time around.
- Deterministic scalar value: 25:50 time
"""

    answer = ExecutorAgent(model_interface=None)._extract_deterministic_aggregation_answer(  # type: ignore[arg-type]
        "What was my personal best time in the charity 5K run?",
        fact_sheet,
    )

    assert answer == "25:50"


def test_executor_prefers_latest_money_ledger_for_preapproval_question() -> None:
    fact_sheet = """
Money ledger:
- money_ledger={"amount": 350000.0, "currency": "USD", "location_scope": ["wells fargo"], "purpose": "wells fargo", "source": "I got pre-approved for $350,000 from Wells Fargo", "verb": "money"}
- money_ledger={"amount": 400000.0, "currency": "USD", "location_scope": ["wells fargo"], "purpose": "wells fargo", "source": "I later got pre-approval for $400,000 from Wells Fargo", "verb": "money"}
"""

    answer = ExecutorAgent(model_interface=None)._extract_deterministic_aggregation_answer(  # type: ignore[arg-type]
        "What was the amount I was pre-approved for when I got my mortgage from Wells Fargo?",
        fact_sheet,
    )

    assert answer == "$400,000"


def test_executor_extracts_latest_camera_lens_type() -> None:
    fact_sheet = """
[1] Time：2023-03-11 03-12-00
Relevant lines:
- Speaking of lenses, I recently got a new 50mm prime lens, which has been working out great.

[2] Time：2023-08-30 14-23-00
Relevant lines:
- By the way, I recently took some great shots with my 70-200mm zoom lens at a local park.
"""

    answer = ExecutorAgent(model_interface=None)._extract_deterministic_aggregation_answer(  # type: ignore[arg-type]
        "What type of camera lens did I purchase most recently?",
        fact_sheet,
    )

    assert answer == "a 70-200mm zoom lens"


def test_executor_formats_boolean_answer_to_yes() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: My mom is actually using the same grocery list app as me now.
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "Is my mom using the same grocery list method as me?",
        "Based on the provided evidence, it appears that my mom is indeed using the same grocery list app as me now.",
        fact_sheet,
    )

    assert answer == "Yes."


def test_executor_uses_direct_fact_for_refusal_like_text_answers() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: Rachel moved back to the suburbs again.
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "Where did Rachel move to after her recent relocation?",
        "Based on the provided evidence, the exact neighborhood is not explicitly stated.",
        fact_sheet,
    )

    assert answer == "the suburbs"


def test_executor_boolean_override_for_same_grocery_list_app() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I was just thinking, my mom is actually using the same grocery list app as me now, so we can easily share lists.
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "Is my mom using the same grocery list method as me?",
        "No.",
        fact_sheet,
    )

    assert answer == "Yes."


def test_executor_boolean_override_for_spare_screwdriver_question() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I need to open up my laptop to clean the fans soon, do I have a spare screwdriver for that?
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "Do I have a spare screwdriver for opening up my laptop?",
        "According to the available evidence, I cannot confirm whether you have a spare screwdriver for opening up your laptop.",
        fact_sheet,
    )

    assert answer == "Yes."


def test_executor_forces_refusal_when_fact_sheet_has_missing_anchor() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I see Dr. Smith every week.

Evidence chain assessment:

- evidence_confidence=low

- verifier_action=refuse

- reason_codes=relation_mismatch,missing_anchor,missing_dr_johnson,competing_dr_smith,doctor_name

- missing_slots=Dr. Johnson
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "How often do I see Dr. Johnson?",
        "every week",
        fact_sheet,
    )

    assert answer == "The information provided is not enough. You mentioned seeing Dr. Smith but not Dr. Johnson."


def test_executor_forces_targeted_role_refusal_even_with_deterministic_transition() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I lead a team of 4 engineers in my new role as Senior Software Engineer.
- Deterministic state transition: previous = 4 engineers ; current = 5 engineers

Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_software_engineer_manager,competing_senior_software_engineer,role_title
- missing_slots=Software Engineer Manager
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "How many engineers do I lead when I just started my new role as Software Engineer Manager?",
        "5",
        fact_sheet,
    )

    assert (
        answer
        == "The information provided is not enough. You mentioned starting the role as Senior Software Engineer but not Software Engineer Manager."
    )


def test_build_aggregation_notes_supports_how_many_times_word_counts() -> None:
    results = [
        {
            "timestamp": "2023-05-30T17:45:00",
            "user_query": "That's six times now that I've worn my new black Converse Chuck Taylor All Star sneakers.",
            "summary": "That's six times now that I've worn my new black Converse Chuck Taylor All Star sneakers.",
            "assistant_response": "",
        }
    ]

    notes = tools._build_aggregation_notes(
        "How many times have I worn my new black Converse Chuck Taylor All Star sneakers?",
        results,
    )

    assert any("Deterministic item count: 6" in note for note in notes)


def test_executor_keeps_deterministic_count_over_conflicting_direct_fact() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I did attend three sessions of the bereavement support group.
- Deterministic item count: 5

Reasoning workspace:
- deterministic_answer=5
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "How many sessions of the bereavement support group did I attend?",
        "5",
        fact_sheet,
    )

    assert answer == "5"


def test_executor_extracts_current_old_sneakers_location_from_closet_line() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I need to organize my closet this weekend, and I'm looking forward to storing my old sneakers in a shoe rack in my closet.
- Atomic fact: I've been keeping my old sneakers under my bed for storage.
"""

    answer = ExecutorAgent(model_interface=None)._extract_direct_location_answer(  # type: ignore[arg-type]
        "Where do I currently keep my old sneakers?",
        fact_sheet,
    )

    assert answer == "in a shoe rack in my closet"


def test_executor_keeps_initial_old_sneakers_location_when_question_is_initial() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I need to organize my closet this weekend, and I'm looking forward to storing my old sneakers in a shoe rack in my closet.
- Atomic fact: I've been keeping my old sneakers under my bed for storage.
"""

    answer = ExecutorAgent(model_interface=None)._extract_direct_location_answer(  # type: ignore[arg-type]
        "Where do I initially keep my old sneakers?",
        fact_sheet,
    )

    assert answer == "under my bed for storage"


def test_executor_extracts_music_shop_location_for_guitar_service() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: And yeah, I remember the music shop on Main St where I got my guitar serviced, they're really good with guitar maintenance.
- Atomic fact: I actually remember my friend mentioning a music shop on Main St called "Rhythm Central" that has a good reputation for guitar servicing.
"""

    answer = ExecutorAgent(model_interface=None)._extract_direct_location_answer(  # type: ignore[arg-type]
        "Where did I get my guitar serviced?",
        fact_sheet,
    )

    assert answer == "the music shop on Main St"


def test_executor_normalizes_painting_location_to_bedroom() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: The painting 'Ethereal Dreams' by Emma Taylor is currently hanging above my bed.
"""

    answer = ExecutorAgent(model_interface=None)._extract_direct_location_answer(  # type: ignore[arg-type]
        "Where is the painting 'Ethereal Dreams' by Emma Taylor currently hanging?",
        fact_sheet,
    )

    assert answer == "in my bedroom"


def test_executor_extracts_vehicle_model_type() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: How do I achieve that weathered look on my Ford F-150 pickup truck model?
- Atomic fact: I'm interested in the Vallejo paints I'm using for this project.
"""

    answer = ExecutorAgent(model_interface=None)._extract_direct_product_type_answer(  # type: ignore[arg-type]
        "What type of vehicle model am I currently working on?",
        fact_sheet,
    )

    assert answer == "Ford F-150 pickup truck"


def test_executor_does_not_force_refusal_for_supported_apartment_duration() -> None:
    fact_sheet = """
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_harajuku,competing_tokyo,location
- missing_slots=Harajuku

Aggregation worksheet:
- Atomic fact: I moved into my current apartment in Harajuku three months ago.
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "How long have I been living in my current apartment in Harajuku?",
        "3 months",
        fact_sheet,
    )

    assert answer == "3 months"


def test_executor_forces_apartment_location_refusal_when_target_only_appears_in_irrelevant_context() -> None:
    fact_sheet = """
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_my_current_apartment,competing_tokyo,location
- missing_slots=my current apartment

Aggregation worksheet:
- Atomic fact: I'm also thinking of inviting some friends who live in Tokyo to join me for a few days.
Event ledger:
- event_ledger={"location":["tokyo","shinjuku"],"source":"Several bus companies operate from Tokyo's Shinjuku Expressway Bus Terminal to Nagano City."}
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "How long have I been living in my current apartment in Shinjuku?",
        "1 hour",
        fact_sheet,
    )

    assert answer == "The information provided is not enough. You mentioned living in Tokyo but not Shinjuku."


def test_named_anchor_targets_ignore_generic_current_apartment_phrase() -> None:
    assert tools._extract_named_anchor_targets("How long have I been living in my current apartment in Harajuku?") == [
        ("location", "harajuku")
    ]


def test_executor_extracts_direct_negroni_frequency_answer() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I've been perfecting my Negroni game - I've tried making it at home 10 times now since my friend Emma showed me how to make it.
"""

    answer = ExecutorAgent(model_interface=None)._extract_direct_fact_answer(  # type: ignore[arg-type]
        "How many times have I tried making a Negroni at home since my friend Emma showed me how to make it?",
        fact_sheet,
    )

    assert answer == "10"


def test_executor_keeps_met_up_count_in_descriptive_form() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, speaking of Germany, I've got a friend Alex from there who I met at a music festival, and we've met up twice already - he's really cool.
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "How many times have I met up with Alex from Germany?",
        "The information provided is not enough. You did not mention this information.",
        fact_sheet,
    )

    assert answer == "We've met up twice."


def test_executor_keeps_deterministic_scalar_over_conflicting_direct_fact() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: Rachel moved to a new apartment in the city.
- Deterministic scalar value: the suburbs
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "Where did Rachel move to after her recent relocation?",
        "the suburbs",
        fact_sheet,
    )

    assert answer == "the suburbs"


def test_executor_refuses_deterministic_answer_when_contract_gap_requires_refusal() -> None:
    fact_sheet = """
Aggregation worksheet:
- Deterministic item count: 2
"""

    with patch(
        "executor.extract_evidence_chain_assessment",
        return_value={
            "verifier_action": "refuse",
            "reason_codes": ["contract_gate_fail", "state-transition-gap", "state_timeline_gap"],
        },
    ):
        answer = ExecutorAgent(model_interface=None)._extract_deterministic_aggregation_answer(  # type: ignore[arg-type]
            "How many engineers do I lead when I just started my new role as Software Engineer Manager?",
            fact_sheet,
        )

    assert answer == ""


def test_build_fact_card_filters_conversational_noise_entities() -> None:
    fact_card = build_fact_card(
        {
            "timestamp": "2024-05-05T10:00:00",
            "user_query": "Can you remember that Rachel moved to Denver?",
            "assistant_response": "",
            "semantic_summary": "Rachel moved to Denver.",
            "language": "en",
            "key_entities": ["Can", "Rachel", "Denver"],
            "memory_profile": {
                "entity_cards": [{"name": "I'm"}, {"name": "Rachel"}, {"name": "Denver"}],
                "event_cards": [],
            },
        },
        "memory\\2024-05-05\\10-00-00.json",
    )

    assert "Rachel" in fact_card["entities"]
    assert "Denver" in fact_card["entities"]
    assert "Can" not in fact_card["entities"]
    assert "I'm" not in fact_card["entities"]


def test_state_time_intent_keeps_so_far_purchase_count_as_current_only() -> None:
    intent = tools._extract_state_time_intent("How many tops have I bought from H&M so far?")

    assert intent["ask_current"] is True
    assert intent["ask_update_resolution"] is False
    assert intent["ask_transition"] is False


def test_state_time_intent_treats_before_purchase_question_as_previous_only() -> None:
    intent = tools._extract_state_time_intent(
        "Before I purchased the gravel bike, do I have other bikes in addition to my mountain bike and my commuter bike?"
    )

    assert intent["ask_previous"] is True
    assert intent["ask_current"] is False
    assert intent["ask_update_resolution"] is False
    assert intent["ask_transition"] is False


def test_state_focus_phrase_extracts_where_keep_subject() -> None:
    assert tools._extract_state_focus_phrase("Where do I initially keep my old sneakers?") == "sneakers"


def test_state_time_intent_marks_recent_increase_decrease_question_as_transition() -> None:
    intent = tools._extract_state_time_intent(
        "Did I most recently increase or decrease the limit on the number of cups of coffee in the morning?"
    )

    assert intent["ask_transition"] is True
    assert intent["focus"] == "cups of coffee in morning"


def test_executor_prefers_current_total_for_so_far_purchase_question() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I've already got five tops from H&M so far, and I'm thinking of getting a few more
- Atomic fact: I've already bought three tops from H&M, I'm really loving their summer collection
- Deterministic state transition: previous = 3 tops ; current = 5 tops
- Intermediate verification: previous_value=3 tops, current_value=5 tops
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "How many tops have I bought from H&M so far?",
        "2",
        fact_sheet,
    )

    assert answer == "5"


def test_timed_fact_returns_previous_personal_best_time() -> None:
    fact_sheet = """
[1] Time：2023-05-04 17-00-00
Summary：I set a new personal best of 26 minutes and 30 seconds in the charity 5K run.
Relevant lines:
- I set a new personal best of 26 minutes and 30 seconds in the charity 5K run.

[2] Time：2023-04-11 13-31-00
Summary：I've recently completed a charity 5K run with a personal best time of 27 minutes and 45 seconds.
Relevant lines:
- I've recently completed a charity 5K run with a personal best time of 27 minutes and 45 seconds.
"""

    answer = ExecutorAgent(model_interface=None)._extract_timed_fact_answer(  # type: ignore[arg-type]
        "What was my previous personal best time for the charity 5K run?",
        fact_sheet,
    )

    assert answer == "27 minutes and 45 seconds"


def test_executor_prefers_previous_personal_best_time_over_newer_answer() -> None:
    fact_sheet = """
[1] Time：2023-05-04 17-00-00
Summary：I set a new personal best of 26 minutes and 30 seconds in the charity 5K run.
Relevant lines:
- I set a new personal best of 26 minutes and 30 seconds in the charity 5K run.

[2] Time：2023-04-11 13-31-00
Summary：I've recently completed a charity 5K run with a personal best time of 27 minutes and 45 seconds.
Relevant lines:
- I've recently completed a charity 5K run with a personal best time of 27 minutes and 45 seconds.
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "What was my previous personal best time for the charity 5K run?",
        "Your previous personal best time for the charity 5K run was 26 minutes and 30 seconds.",
        fact_sheet,
    )

    assert answer == "27 minutes and 45 seconds"


def test_executor_extracts_kitchen_gadget_before_air_fryer() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I'm actually thinking of using my new Instant Pot to make some of these soups and stews.
- Atomic fact: I'm actually thinking of using the Air Fryer I got yesterday to make some crispy sweet potato fries.
"""

    answer = ExecutorAgent(model_interface=None)._extract_direct_fact_answer(  # type: ignore[arg-type]
        "What new kitchen gadget did I invest in before getting the Air Fryer?",
        fact_sheet,
    )

    assert answer == "Instant Pot"


def test_executor_answers_yes_for_other_bike_before_gravel_purchase() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I'll have my road bike, and I'm planning to bring all my bikes, so I'll need to find accommodations with bike storage.
- Atomic fact: I'm particularly interested in joining a guided tour in Jackson Hole to explore some of the more challenging mountain bike trails.
"""

    answer = ExecutorAgent(model_interface=None)._enforce_english_answer_shape(  # type: ignore[arg-type]
        "Before I purchased the gravel bike, do I have other bikes in addition to my mountain bike and my commuter bike?",
        "According to the available information, I cannot confirm whether you have other bikes besides your mountain bike and commuter bike before purchasing the gravel bike.",
        fact_sheet,
    )

    assert answer == "Yes. (You have a road bike too.)"
