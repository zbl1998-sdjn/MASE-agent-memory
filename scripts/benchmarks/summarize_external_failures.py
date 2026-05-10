from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


BACKEND_ERROR_MARKERS = (
    "responseerror",
    "status code",
    "connection",
    "connecterror",
    "timeout",
    "readtimeout",
    "remoteprotocolerror",
    "rate limit",
    "service unavailable",
)

REFUSAL_MARKERS = (
    "cannot answer",
    "can't answer",
    "cannot determine",
    "can't determine",
    "unable to answer",
    "unable to determine",
    "not enough information",
    "insufficient information",
    "not mentioned",
    "not specified",
    "not provided",
    "i don't know",
    "i do not know",
)


def _load_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("rows") or payload.get("details")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise ValueError(f"Unsupported external result shape: {path}")


def _string_value(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        return str(value)
    return ""


def _response_text(row: dict[str, Any]) -> str:
    return _string_value(row.get("response"), row.get("raw_prediction"), row.get("raw_pred"), row.get("prediction"), row.get("pred"))


def _is_passed(row: dict[str, Any]) -> bool:
    for key in ("metric_value", "metric"):
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return value > 0
    status = str(row.get("status") or "").lower()
    return status in {"pass", "passed", "ok_passed"}


def classify_failure(row: dict[str, Any]) -> str:
    if _is_passed(row):
        return "passed"

    error = _string_value(row.get("error"))
    lowered_error = error.lower()
    if error:
        if any(marker in lowered_error for marker in BACKEND_ERROR_MARKERS):
            return "model_backend_error"
        return "adapter_error"

    if _looks_like_format_failure(row):
        return "format_failure"

    response = _response_text(row)
    lowered_response = response.lower()
    if not response:
        return "empty_response"
    if any(marker in lowered_response for marker in REFUSAL_MARKERS):
        return "model_refusal_or_evidence_miss"
    if _has_scoring_signal(row):
        return "answer_mismatch_or_reasoning_failure"
    return "unscored_failure"


def _looks_like_format_failure(row: dict[str, Any]) -> bool:
    task = str(row.get("task") or "").lower()
    prediction = row.get("prediction", row.get("pred"))
    if task in {"showssort", "reportsumsort"} and not isinstance(prediction, list):
        return True
    if str(row.get("status") or "").lower() in {"parse_error", "format_error"}:
        return True
    return False


def _has_scoring_signal(row: dict[str, Any]) -> bool:
    return any(key in row for key in ("metric_value", "metric", "dataset_answer", "answer", "gold_answers"))


def _preview(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _row_label(row: dict[str, Any], fallback_index: int) -> str:
    return _string_value(row.get("id"), row.get("test_name"), row.get("question_id"), f"row-{fallback_index}")


def build_report(input_paths: list[Path], max_examples: int = 3) -> dict[str, Any]:
    buckets: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total_rows = 0

    for input_path in input_paths:
        rows = _load_json_or_jsonl(input_path)
        for index, row in enumerate(rows, start=1):
            total_rows += 1
            bucket = classify_failure(row)
            buckets[bucket] += 1
            if len(examples[bucket]) >= max_examples:
                continue
            examples[bucket].append(
                {
                    "input_path": str(input_path),
                    "row": _row_label(row, index),
                    "task": _string_value(row.get("task"), row.get("question_type"), row.get("suite")),
                    "error": _preview(row.get("error")),
                    "response": _preview(_response_text(row)),
                    "expected": _preview(_string_value(row.get("dataset_answer"), row.get("answer"), row.get("gold_answers"))),
                    "prediction": _preview(_string_value(row.get("prediction"), row.get("pred"), row.get("metric_value"))),
                }
            )

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "inputs": [str(path) for path in input_paths],
        "total_rows": total_rows,
        "buckets": dict(sorted(buckets.items())),
        "examples": {bucket: items for bucket, items in sorted(examples.items())},
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# External Generalization Failure Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Inputs: {len(report['inputs'])}",
        f"- Rows: {report['total_rows']}",
        "",
        "## Buckets",
        "",
        "| Bucket | Count |",
        "|---|---:|",
    ]
    for bucket, count in report["buckets"].items():
        lines.append(f"| {bucket} | {count} |")

    lines.extend(["", "## Examples", ""])
    for bucket, examples in report["examples"].items():
        lines.append(f"### {bucket}")
        if not examples:
            lines.append("")
            continue
        for example in examples:
            lines.extend(
                [
                    f"- Row: `{example['row']}`",
                    f"  - Input: `{example['input_path']}`",
                    f"  - Task: `{example['task']}`",
                    f"  - Error: {example['error'] or '-'}",
                    f"  - Response: {example['response'] or '-'}",
                    f"  - Expected: {example['expected'] or '-'}",
                    f"  - Prediction: {example['prediction'] or '-'}",
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize BAMBOO/NoLiMa external benchmark failures.")
    parser.add_argument("--input", action="append", required=True, help="Result JSON/JSONL path. May be repeated.")
    parser.add_argument("--output", type=Path, default=None, help="Markdown report output path.")
    parser.add_argument("--json-output", type=Path, default=None, help="Structured JSON report output path.")
    parser.add_argument("--max-examples", type=int, default=3, help="Examples to keep per bucket.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_paths = [Path(path).expanduser().resolve() for path in args.input]
    missing = [path for path in input_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing input file(s): {', '.join(str(path) for path in missing)}")

    report = build_report(input_paths, max_examples=max(0, args.max_examples))
    markdown = render_markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
