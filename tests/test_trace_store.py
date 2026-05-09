from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase.trace_recorder import (
    COMPONENT_SOURCE_FILES,
    get_trace_by_id,
    list_trace_summaries,
    read_trace_rows,
    summarize_trace,
)


def _write_jsonl(path: Path, rows: list[dict[str, Any]], *, bad_line: bool = False) -> None:
    lines = [json.dumps(rows[0], ensure_ascii=False)]
    if bad_line:
        lines.append("{not-json")
    lines.extend(json.dumps(row, ensure_ascii=False) for row in rows[1:])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sample_rows() -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "mase.trace.v1",
            "trace_id": "trace-cloud-risk",
            "created_at": "2026-01-01T00:00:00+00:00",
            "user_question": "服务器端口是多少？",
            "route": {"action": "search_memory"},
            "answer": "端口是 9909。" * 30,
            "search_results": [{"_source": "entity_state", "risk_flags": ["scope_mismatch:thread"]}],
            "evidence_assessment": {
                "risk_flags": ["stale_candidate"],
                "model_call_summary": {"call_count": 1, "total_tokens": 120, "estimated_cost_usd": 0.0014},
                "model_calls": [
                    {
                        "provider": "openai",
                        "model_name": "gpt-4o-mini",
                        "is_local": False,
                        "total_tokens": 120,
                        "estimated_cost_usd": 0.0014,
                        "request_headers": {"Authorization": "Bearer secret"},
                    }
                ],
            },
            "steps": [
                {
                    "name": "route_decision",
                    "component": "router",
                    "source_file": COMPONENT_SOURCE_FILES["router"],
                },
                {
                    "name": "memory_retrieval",
                    "component": "retrieval",
                    "source_file": COMPONENT_SOURCE_FILES["retrieval"],
                },
            ],
        },
        {
            "schema_version": "mase.trace.v1",
            "trace_id": "trace-local-clean",
            "user_question": "本地问题",
            "route": {"action": "answer_direct"},
            "answer": "本地回答",
            "evidence_assessment": {
                "model_call_summary": {"call_count": 1, "cloud_call_count": 0, "total_tokens": 8},
            },
            "steps": [
                {
                    "name": "executor_answer",
                    "component": "executor",
                    "source_file": COMPONENT_SOURCE_FILES["executor"],
                }
            ],
        },
    ]


def test_read_trace_rows_loads_multiline_jsonl_and_reports_bad_lines(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    _write_jsonl(trace_path, _sample_rows(), bad_line=True)

    result = read_trace_rows(trace_path)

    assert [row["trace_id"] for row in result["rows"]] == ["trace-cloud-risk", "trace-local-clean"]
    assert result["metadata"]["line_count"] == 3
    assert result["metadata"]["row_count"] == 2
    assert result["metadata"]["skipped_count"] == 1
    assert result["metadata"]["skipped_lines"][0]["line_number"] == 2


def test_trace_summary_fields_are_safe_and_complete() -> None:
    summary = summarize_trace(_sample_rows()[0])

    assert summary["trace_id"] == "trace-cloud-risk"
    assert summary["schema_version"] == "mase.trace.v1"
    assert summary["created_at"] == "2026-01-01T00:00:00+00:00"
    assert summary["user_question"] == "服务器端口是多少？"
    assert summary["route_action"] == "search_memory"
    assert summary["answer_preview"].endswith("...")
    assert summary["step_count"] == 2
    assert summary["components"] == ["retrieval", "router"]
    assert summary["source_files"] == [COMPONENT_SOURCE_FILES["retrieval"], COMPONENT_SOURCE_FILES["router"]]
    assert summary["has_cloud_call"] is True
    assert summary["estimated_cost_usd"] == 0.0014
    assert summary["total_tokens"] == 120
    assert summary["risk_flags"] == ["scope_mismatch:thread", "stale_candidate"]
    assert summary["model_call_summary"] == {
        "call_count": 1,
        "cloud_call_count": 1,
        "models": ["gpt-4o-mini"],
        "providers": ["openai"],
        "total_tokens": 120,
        "estimated_cost_usd": 0.0014,
        "has_cloud_call": True,
    }
    assert "Authorization" not in json.dumps(summary, ensure_ascii=False)


def test_list_trace_summaries_filters_supported_conditions(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    _write_jsonl(trace_path, _sample_rows())

    assert _ids(list_trace_summaries(trace_path, route_action="search_memory")) == ["trace-cloud-risk"]
    assert _ids(list_trace_summaries(trace_path, component="executor")) == ["trace-local-clean"]
    assert _ids(list_trace_summaries(trace_path, source_file=COMPONENT_SOURCE_FILES["retrieval"])) == [
        "trace-cloud-risk"
    ]
    assert _ids(list_trace_summaries(trace_path, has_cloud_call=True)) == ["trace-cloud-risk"]
    assert _ids(list_trace_summaries(trace_path, min_cost=0.001, max_cost=0.002)) == ["trace-cloud-risk"]
    assert _ids(list_trace_summaries(trace_path, has_risk=True)) == ["trace-cloud-risk"]
    assert _ids(list_trace_summaries(trace_path, trace_id="trace-local-clean")) == ["trace-local-clean"]

    limited = list_trace_summaries(trace_path, limit=1)
    assert _ids(limited) == ["trace-cloud-risk"]
    assert limited["metadata"]["matched_count"] == 2
    assert limited["metadata"]["returned_count"] == 1


def test_get_trace_by_id_returns_full_trace(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    _write_jsonl(trace_path, _sample_rows())

    trace = get_trace_by_id(trace_path, "trace-local-clean")

    assert trace is not None
    assert trace["answer"] == "本地回答"
    assert get_trace_by_id(trace_path, "missing") is None


def test_legacy_trace_missing_new_fields_does_not_crash() -> None:
    summary = summarize_trace({"trace_id": "legacy", "route": {"action": "legacy_action"}})

    assert summary["trace_id"] == "legacy"
    assert summary["created_at"] is None
    assert summary["answer_preview"] == ""
    assert summary["step_count"] == 0
    assert summary["components"] == []
    assert summary["source_files"] == []
    assert summary["model_call_summary"]["call_count"] == 0
    assert summary["has_cloud_call"] is False
    assert summary["estimated_cost_usd"] == 0.0
    assert summary["total_tokens"] == 0
    assert summary["risk_flags"] == []


def _ids(result: dict[str, Any]) -> list[str | None]:
    return [summary["trace_id"] for summary in result["summaries"]]
