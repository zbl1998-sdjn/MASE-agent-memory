from __future__ import annotations

from typing import Any

from mase.golden_tests import run_golden_tests


class FakeMemory:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def search_memory(
        self,
        keywords,
        *,
        full_query=None,
        limit=5,
        include_history=False,
        scope_filters=None,
    ):
        del keywords, full_query, include_history, scope_filters
        return self.rows[:limit]


def test_golden_tests_pass_release_gate_when_critical_cases_pass() -> None:
    report = run_golden_tests(
        FakeMemory([{"entity_key": "owner", "entity_value": "Alice"}]),
        [
            {
                "case_id": "owner",
                "query": "project owner",
                "expected_terms": ["Alice"],
                "severity": "critical",
            }
        ],
        scope={},
    )

    assert report["summary"]["release_gate"] == "passed"
    assert report["results"][0]["verdict"] == "passed"


def test_golden_tests_block_release_on_critical_failure() -> None:
    report = run_golden_tests(
        FakeMemory([{"entity_key": "owner", "entity_value": "Bob"}]),
        [
            {
                "case_id": "owner",
                "query": "project owner",
                "expected_terms": ["Alice"],
                "severity": "critical",
            }
        ],
        scope={},
    )

    assert report["summary"]["release_gate"] == "blocked"
    assert report["summary"]["critical_failed_count"] == 1
