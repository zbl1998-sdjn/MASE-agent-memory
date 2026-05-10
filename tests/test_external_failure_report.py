from __future__ import annotations

import json

from scripts.benchmarks.summarize_external_failures import build_report, classify_failure, render_markdown


def test_external_failure_classifier_detects_backend_errors() -> None:
    row = {"error": "ResponseError:  (status code: 502)", "response": ""}

    assert classify_failure(row) == "model_backend_error"


def test_external_failure_classifier_separates_refusal_and_mismatch() -> None:
    refusal = {"response": "Cannot answer.", "metric_value": 0}
    mismatch = {"response": "Caleb", "metric_value": 0, "gold_answers": ["Maya"]}

    assert classify_failure(refusal) == "model_refusal_or_evidence_miss"
    assert classify_failure(mismatch) == "answer_mismatch_or_reasoning_failure"


def test_external_failure_report_reads_json_and_jsonl(tmp_path) -> None:
    json_path = tmp_path / "nolima.results.json"
    json_path.write_text(
        json.dumps(
            [
                {"test_name": "case-a", "response": "", "error": "ResponseError: status code: 502"},
                {"test_name": "case-b", "response": "Caleb", "metric_value": 1},
            ]
        ),
        encoding="utf-8",
    )
    jsonl_path = tmp_path / "bamboo.predictions.jsonl"
    jsonl_path.write_text(
        json.dumps({"id": "case-c", "task": "senhallu", "pred": "Maybe", "answer": "Yes.", "metric": 0}) + "\n",
        encoding="utf-8",
    )

    report = build_report([json_path, jsonl_path], max_examples=2)
    markdown = render_markdown(report)

    assert report["total_rows"] == 3
    assert report["buckets"]["model_backend_error"] == 1
    assert report["buckets"]["passed"] == 1
    assert report["buckets"]["answer_mismatch_or_reasoning_failure"] == 1
    assert "External Generalization Failure Report" in markdown
