from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

COMPONENT_SOURCE_FILES: dict[str, str] = {
    "router": "src/mase/router.py",
    "retrieval": "src/mase/memory_service.py",
    "notetaker": "src/mase/notetaker_agent.py",
    "fact_sheet": "src/mase/fact_sheet.py",
    "planner": "src/mase/planner_agent.py",
    "executor": "src/mase/executor.py",
    "model_interface": "src/mase/model_interface.py",
}


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _step(
    *,
    name: str,
    component: str,
    status: str = "success",
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "component": component,
        "source_file": COMPONENT_SOURCE_FILES.get(component, "unknown"),
        "status": status,
        "input": _normalize(input_summary or {}),
        "output": _normalize(output_summary or {}),
    }
    if latency_ms is not None:
        row["latency_ms"] = round(float(latency_ms), 3)
    return row


def build_trace_steps(
    *,
    user_question: str,
    route: Any,
    planner: Any,
    thread: Any,
    executor_target: dict[str, Any],
    answer: str,
    search_results: list[dict[str, Any]],
    fact_sheet: str,
    evidence_assessment: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    route_data = _normalize(route) or {}
    planner_data = _normalize(planner) or {}
    thread_data = _normalize(thread) or {}
    evidence = dict(evidence_assessment or {})
    retrieval_plan = evidence.get("retrieval_plan") or {}
    if not isinstance(retrieval_plan, dict):
        retrieval_plan = {}
    return [
        _step(
            name="route_decision",
            component="router",
            input_summary={"question_chars": len(user_question)},
            output_summary={
                "action": route_data.get("action"),
                "keywords": route_data.get("keywords"),
                "router_observed": evidence.get("router_observed"),
            },
        ),
        _step(
            name="memory_retrieval",
            component="retrieval",
            input_summary={
                "action": route_data.get("action"),
                "keywords": route_data.get("keywords"),
                "retrieval_plan": retrieval_plan,
            },
            output_summary={
                "hit_count": len(search_results),
                "sources": sorted({str(row.get("_source") or "unknown") for row in search_results}),
                "freshness": sorted({str(row.get("freshness") or "unknown") for row in search_results}),
            },
        ),
        _step(
            name="fact_sheet_build",
            component="fact_sheet",
            input_summary={"hit_count": len(search_results), "notetaker_mode": evidence.get("notetaker_mode")},
            output_summary={"fact_sheet_chars": len(fact_sheet), "memory_heat": evidence.get("memory_heat")},
        ),
        _step(
            name="planner_snapshot",
            component="planner",
            input_summary={"thread": thread_data},
            output_summary=planner_data,
        ),
        _step(
            name="executor_answer",
            component="executor",
            input_summary={
                "executor_target": executor_target,
                "collaboration_mode": evidence.get("collaboration_mode"),
            },
            output_summary={"answer_chars": len(answer)},
        ),
    ]


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
    trace_id: str | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> str:
    path_value = str(os.environ.get("MASE_TRACE_RECORD_PATH") or "").strip()
    if not path_value:
        return ""
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence = _normalize(evidence_assessment or {})
    resolved_trace_id = trace_id or (evidence.get("trace_id") if isinstance(evidence, dict) else None)
    resolved_steps = steps or build_trace_steps(
        user_question=user_question,
        route=route,
        planner=planner,
        thread=thread,
        executor_target=executor_target,
        answer=answer,
        search_results=search_results,
        fact_sheet=fact_sheet,
        evidence_assessment=evidence_assessment,
    )
    payload = {
        "schema_version": "mase.trace.v1",
        "trace_id": resolved_trace_id,
        "user_question": user_question,
        "route": _normalize(route),
        "planner": _normalize(planner),
        "thread": _normalize(thread),
        "executor_target": _normalize(executor_target),
        "answer": answer,
        "search_results": _normalize(search_results),
        "fact_sheet": fact_sheet,
        "evidence_assessment": evidence,
        "steps": _normalize(resolved_steps),
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


def read_trace_rows(path: str | Path) -> dict[str, Any]:
    file_path = Path(path).expanduser().resolve()
    metadata: dict[str, Any] = {
        "path": str(file_path),
        "line_count": 0,
        "row_count": 0,
        "skipped_count": 0,
        "skipped_lines": [],
    }
    if not file_path.exists():
        return {"rows": [], "metadata": metadata}

    rows: list[dict[str, Any]] = []
    skipped_lines: list[dict[str, Any]] = []
    with file_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            metadata["line_count"] = line_number
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                skipped_lines.append({"line_number": line_number, "error": exc.msg, "column": exc.colno})
                continue
            if not isinstance(row, dict):
                skipped_lines.append({"line_number": line_number, "error": "trace row is not a JSON object"})
                continue
            rows.append(row)

    metadata["row_count"] = len(rows)
    metadata["skipped_count"] = len(skipped_lines)
    metadata["skipped_lines"] = skipped_lines
    return {"rows": rows, "metadata": metadata}


def summarize_trace(row: dict[str, Any]) -> dict[str, Any]:
    trace = row if isinstance(row, dict) else {}
    evidence = _as_dict(trace.get("evidence_assessment"))
    steps = _as_list(trace.get("steps"))
    model_summary = _safe_model_call_summary(evidence)
    risk_flags = _trace_risk_flags(trace, evidence)
    return {
        "trace_id": _optional_str(trace.get("trace_id")),
        "schema_version": _optional_str(trace.get("schema_version")),
        "created_at": _first_str(
            trace.get("created_at"),
            trace.get("timestamp"),
            trace.get("ts"),
            evidence.get("created_at"),
            evidence.get("timestamp"),
        ),
        "user_question": _safe_text(trace.get("user_question")),
        "route_action": _optional_str(_as_dict(trace.get("route")).get("action")),
        "answer_preview": _preview(trace.get("answer")),
        "step_count": len(steps),
        "components": _sorted_step_values(steps, "component"),
        "source_files": _sorted_step_values(steps, "source_file"),
        "model_call_summary": model_summary,
        "has_cloud_call": bool(model_summary["has_cloud_call"]),
        "estimated_cost_usd": model_summary["estimated_cost_usd"],
        "total_tokens": model_summary["total_tokens"],
        "risk_flags": risk_flags,
    }


def list_trace_summaries(
    path: str | Path,
    *,
    trace_id: str | None = None,
    route_action: str | None = None,
    component: str | None = None,
    source_file: str | None = None,
    has_cloud_call: bool | None = None,
    min_cost: float | None = None,
    max_cost: float | None = None,
    has_risk: bool | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    store = read_trace_rows(path)
    summaries = [
        summary
        for summary in (summarize_trace(row) for row in store["rows"])
        if _summary_matches(
            summary,
            trace_id=trace_id,
            route_action=route_action,
            component=component,
            source_file=source_file,
            has_cloud_call=has_cloud_call,
            min_cost=min_cost,
            max_cost=max_cost,
            has_risk=has_risk,
        )
    ]
    matched_count = len(summaries)
    if limit is not None:
        summaries = summaries[: max(0, int(limit))]
    metadata = {**store["metadata"], "matched_count": matched_count, "returned_count": len(summaries)}
    return {"summaries": summaries, "metadata": metadata}


def get_trace_by_id(path: str | Path, trace_id: str) -> dict[str, Any] | None:
    wanted = str(trace_id)
    for row in read_trace_rows(path)["rows"]:
        if str(row.get("trace_id") or "") == wanted:
            return row
    return None


def _summary_matches(
    summary: dict[str, Any],
    *,
    trace_id: str | None,
    route_action: str | None,
    component: str | None,
    source_file: str | None,
    has_cloud_call: bool | None,
    min_cost: float | None,
    max_cost: float | None,
    has_risk: bool | None,
) -> bool:
    cost = float(summary["estimated_cost_usd"])
    return (
        (trace_id is None or summary["trace_id"] == trace_id)
        and (route_action is None or summary["route_action"] == route_action)
        and (component is None or component in summary["components"])
        and (source_file is None or source_file in summary["source_files"])
        and (has_cloud_call is None or summary["has_cloud_call"] is has_cloud_call)
        and (min_cost is None or cost >= float(min_cost))
        and (max_cost is None or cost <= float(max_cost))
        and (has_risk is None or bool(summary["risk_flags"]) is has_risk)
    )


def _safe_model_call_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    summary = _as_dict(evidence.get("model_call_summary"))
    calls = [item for item in _as_list(evidence.get("model_calls")) if isinstance(item, dict)]
    if calls:
        total_tokens = sum(_int(item.get("total_tokens")) for item in calls)
        estimated_cost = sum(_float(item.get("estimated_cost_usd")) for item in calls)
        cloud_call_count = sum(1 for item in calls if _is_cloud_call(item))
        models = sorted(
            {
                _safe_text(item.get("model_name") or item.get("model"))
                for item in calls
                if _safe_text(item.get("model_name") or item.get("model"))
            }
        )
        providers = sorted({_safe_text(item.get("provider")) for item in calls if _safe_text(item.get("provider"))})
        call_count = len(calls)
    else:
        total_tokens = _int(summary.get("total_tokens"))
        estimated_cost = _float(summary.get("estimated_cost_usd"))
        cloud_call_count = _int(summary.get("cloud_call_count"))
        models = _sorted_strings(summary.get("models") or summary.get("model_names"))
        providers = _sorted_strings(summary.get("providers") or summary.get("provider_names"))
        call_count = _int(summary.get("call_count"))
    has_cloud_call = bool(summary.get("has_cloud_call")) or cloud_call_count > 0
    return {
        "call_count": call_count,
        "cloud_call_count": cloud_call_count,
        "models": models,
        "providers": providers,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(estimated_cost, 8),
        "has_cloud_call": has_cloud_call,
    }


def _trace_risk_flags(trace: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    flags: set[str] = set()
    for source in (trace, evidence):
        flags.update(_sorted_strings(source.get("risk_flags")))
    for item in _as_list(trace.get("search_results")):
        if isinstance(item, dict):
            flags.update(_sorted_strings(item.get("risk_flags")))
    for item in _as_list(evidence.get("hit_inspections")):
        if isinstance(item, dict):
            flags.update(_sorted_strings(item.get("risk_flags")))
    return sorted(flags)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_str(*values: Any) -> str | None:
    for value in values:
        text = _optional_str(value)
        if text is not None:
            return text
    return None


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _preview(value: Any, *, limit: int = 160) -> str:
    text = _safe_text(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _sorted_step_values(steps: list[Any], key: str) -> list[str]:
    return sorted({_safe_text(step.get(key)) for step in steps if isinstance(step, dict) and _safe_text(step.get(key))})


def _sorted_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list | tuple | set):
        return sorted({_safe_text(item) for item in value if _safe_text(item)})
    return []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_cloud_call(item: dict[str, Any]) -> bool:
    if item.get("is_cloud") is True or item.get("has_cloud_call") is True:
        return True
    if item.get("is_local") is False:
        return True
    provider = _safe_text(item.get("provider")).lower()
    return bool(provider and provider not in {"local", "ollama", "llamacpp", "llama.cpp"})


__all__ = [
    "COMPONENT_SOURCE_FILES",
    "build_trace_steps",
    "get_trace_by_id",
    "list_trace_summaries",
    "load_recorded_traces",
    "read_trace_rows",
    "record_trace_payload",
    "summarize_trace",
]
