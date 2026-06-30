from __future__ import annotations

import importlib
import sys
import types
from typing import Any

from benchmarks.benchmark_cases import REPRESENTATIVE_BATTLEFIELDS
from mase_tools.core import extract_question_scope_filters
from mase_tools.math import calculate
from mase_tools.memory import browse_date, search_memory, write_interaction


def test_placeholder_tool_modules_return_stable_shapes() -> None:
    assert calculate("1 + 1") == {"result": "Calculation placeholder"}
    assert extract_question_scope_filters("budget last week") == {"query": "budget last week"}
    assert search_memory("budget") == [{"content": "Memory entry for budget"}]
    assert browse_date("2023-01-01") == []
    assert write_interaction("noted") is None
    assert {case["id"] for case in REPRESENTATIVE_BATTLEFIELDS} >= {
        "memory-updated-port",
        "math-word-problem",
    }


def test_memory_test_db_demo_import_runs_against_fake_db_core(monkeypatch) -> None:
    fake_db = types.ModuleType("db_core")
    events: list[dict[str, Any]] = []
    facts: dict[str, dict[str, str]] = {}

    def add_event_log(thread_id: str, role: str, content: str) -> None:
        events.append({"thread_id": thread_id, "role": role, "content": content})

    def search_event_log(terms: list[str]) -> list[dict[str, Any]]:
        return [
            {"score": -index, "content": event["content"]}
            for index, event in enumerate(events, start=1)
            if any(term in event["content"] for term in terms)
        ]

    def upsert_entity_fact(category: str, entity_key: str, entity_value: str) -> None:
        facts.setdefault(category, {})[entity_key] = entity_value

    def get_entity_facts(category: str) -> list[dict[str, str]]:
        return [
            {
                "entity_key": key,
                "entity_value": value,
                "updated_at": "2023-01-01T00:00:00",
            }
            for key, value in facts.get(category, {}).items()
        ]

    fake_db.add_event_log = add_event_log
    fake_db.search_event_log = search_event_log
    fake_db.upsert_entity_fact = upsert_entity_fact
    fake_db.get_entity_facts = get_entity_facts
    monkeypatch.setitem(sys.modules, "db_core", fake_db)
    sys.modules.pop("mase_tools.memory.test_db", None)

    importlib.import_module("mase_tools.memory.test_db")

    assert len(events) == 3
    assert facts["finance_budget"]["project_budget"] == "$1000"
