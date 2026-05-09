from __future__ import annotations

from typing import Any

from mase.synthetic_replay import run_synthetic_replay


class FakeMemory:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.scope_filters: dict[str, Any] | None = None

    def search_memory(
        self,
        keywords,
        *,
        full_query=None,
        limit=5,
        include_history=False,
        scope_filters=None,
    ):
        del keywords, full_query, include_history
        self.scope_filters = scope_filters
        return self.rows[:limit]


def test_synthetic_replay_marks_expected_terms_passed() -> None:
    memory = FakeMemory([{"entity_key": "owner", "entity_value": "Alice"}])

    report = run_synthetic_replay(
        memory,
        [{"case_id": "owner", "query": "project owner", "expected_terms": ["Alice"]}],
        scope={"tenant_id": "tenant-a"},
    )

    assert report["summary"]["passed_count"] == 1
    assert report["results"][0]["status"] == "passed"
    assert memory.scope_filters == {"tenant_id": "tenant-a"}


def test_synthetic_replay_flags_missing_and_forbidden_terms() -> None:
    memory = FakeMemory([{"entity_key": "owner", "entity_value": "Bob legacy value"}])

    report = run_synthetic_replay(
        memory,
        [
            {
                "case_id": "owner",
                "query": "project owner",
                "expected_terms": ["Alice"],
                "forbidden_terms": ["Bob"],
            }
        ],
        scope={},
    )

    result = report["results"][0]
    assert report["summary"]["failed_count"] == 1
    assert result["missing_expected_terms"] == ["Alice"]
    assert result["found_forbidden_terms"] == ["Bob"]
