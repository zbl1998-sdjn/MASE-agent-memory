from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from integrations.openai_compat import trace_routes
from integrations.openai_compat.server import app
from mase.trace_recorder import COMPONENT_SOURCE_FILES


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
            "answer": "端口是 9909。",
            "search_results": [{"_source": "entity_state", "risk_flags": ["scope_mismatch:thread"]}],
            "evidence_assessment": {
                "risk_flags": ["stale_candidate"],
                "model_calls": [
                    {
                        "provider": "openai",
                        "model_name": "gpt-test",
                        "is_local": False,
                        "total_tokens": 120,
                        "estimated_cost_usd": 0.0014,
                        "request_headers": {"Authorization": "Bearer secret-key"},
                        "api_key": "secret-key",
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
            "created_at": "2026-01-01T00:01:00+00:00",
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


def test_trace_list_api_returns_summaries_and_metadata(tmp_path: Path, monkeypatch) -> None:
    trace_path = tmp_path / "mase_traces.jsonl"
    _write_jsonl(trace_path, _sample_rows(), bad_line=True)
    monkeypatch.setenv("MASE_TRACE_RECORD_PATH", str(trace_path))
    client = TestClient(app)

    response = client.get("/v1/ui/traces")

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "mase.ui.traces"
    assert [item["trace_id"] for item in payload["data"]["summaries"]] == ["trace-cloud-risk", "trace-local-clean"]
    assert payload["metadata"]["path"] == str(trace_path.resolve())
    assert payload["metadata"]["row_count"] == 2
    assert payload["metadata"]["skipped_count"] == 1
    assert payload["metadata"]["matched_count"] == 2
    assert payload["metadata"]["returned_count"] == 2


def test_trace_list_api_filters_query_params(tmp_path: Path, monkeypatch) -> None:
    trace_path = tmp_path / "mase_traces.jsonl"
    _write_jsonl(trace_path, _sample_rows())
    monkeypatch.setenv("MASE_TRACE_RECORD_PATH", str(trace_path))
    client = TestClient(app)

    response = client.get(
        "/v1/ui/traces",
        params={
            "route_action": "search_memory",
            "component": "retrieval",
            "source_file": COMPONENT_SOURCE_FILES["retrieval"],
            "has_cloud_call": "true",
            "min_cost": "0.001",
            "max_cost": "0.002",
            "has_risk": "true",
            "limit": "1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["trace_id"] for item in payload["data"]["summaries"]] == ["trace-cloud-risk"]
    assert payload["metadata"]["matched_count"] == 1
    assert payload["metadata"]["returned_count"] == 1


def test_trace_detail_api_returns_full_trace_without_provider_secrets(tmp_path: Path, monkeypatch) -> None:
    trace_path = tmp_path / "mase_traces.jsonl"
    _write_jsonl(trace_path, _sample_rows())
    monkeypatch.setenv("MASE_TRACE_RECORD_PATH", str(trace_path))
    client = TestClient(app)

    response = client.get("/v1/ui/traces/trace-cloud-risk")

    assert response.status_code == 200
    payload = response.json()
    trace = payload["data"]["trace"]
    assert payload["object"] == "mase.ui.trace"
    assert trace["trace_id"] == "trace-cloud-risk"
    assert trace["route"]["action"] == "search_memory"
    assert trace["answer"] == "端口是 9909。"
    assert len(trace["steps"]) == 2
    serialized = json.dumps(trace, ensure_ascii=False)
    assert "request_headers" not in serialized
    assert "Authorization" not in serialized
    assert "secret-key" not in serialized


def test_trace_detail_api_missing_returns_404(tmp_path: Path, monkeypatch) -> None:
    trace_path = tmp_path / "mase_traces.jsonl"
    _write_jsonl(trace_path, _sample_rows())
    monkeypatch.setenv("MASE_TRACE_RECORD_PATH", str(trace_path))
    client = TestClient(app)

    response = client.get("/v1/ui/traces/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "trace_not_found"


def test_trace_list_api_default_missing_path_returns_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MASE_TRACE_RECORD_PATH", raising=False)
    monkeypatch.setattr(trace_routes, "ROOT", tmp_path)
    client = TestClient(app)

    response = client.get("/v1/ui/traces")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["summaries"] == []
    assert payload["metadata"]["path"] == str((tmp_path / "memory" / "traces.jsonl").resolve())
    assert payload["metadata"]["row_count"] == 0
    assert payload["metadata"]["skipped_count"] == 0
    assert payload["metadata"]["matched_count"] == 0
    assert payload["metadata"]["returned_count"] == 0
