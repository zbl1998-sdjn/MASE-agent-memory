from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def record_trace_payload(
    *,
    user_question: str,
    route: Any,
    planner: Any,
    thread: Any,
    executor_target: dict[str, Any],
    answer: str,
    search_results: list[dict[str, Any]],
    fact_sheet: str,
    evidence_assessment: dict[str, Any] | None,
) -> str:
    path_value = str(os.environ.get("MASE_TRACE_RECORD_PATH") or "").strip()
    if not path_value:
        return ""
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "user_question": user_question,
        "route": _normalize(route),
        "planner": _normalize(planner),
        "thread": _normalize(thread),
        "executor_target": _normalize(executor_target),
        "answer": answer,
        "search_results": _normalize(search_results),
        "fact_sheet": fact_sheet,
        "evidence_assessment": _normalize(evidence_assessment or {}),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return str(path)


def load_recorded_traces(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


__all__ = ["record_trace_payload", "load_recorded_traces"]
