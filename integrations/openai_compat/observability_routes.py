from __future__ import annotations

import time
from collections import Counter
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from integrations.openai_compat.auth_dependencies import is_read_only_mode
from integrations.openai_compat.responses import response_object, scope_from_query, source_counts
from integrations.openai_compat.runtime import FRONTEND_DIST, SERVER_CONFIG_PATH, memory_service
from mase import describe_models, get_system
from mase.auth_policy import read_internal_api_key
from mase.cost_center import build_cost_center, load_pricing_catalog
from mase.metrics import get_metrics

router = APIRouter()


def _count_by(rows: list[dict[str, Any]], key: str, fallback: str = "unknown") -> list[dict[str, Any]]:
    counts = Counter(str(row.get(key) or fallback) for row in rows)
    return [{"name": name, "value": value} for name, value in counts.most_common()]


def _parse_date_bucket(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else "unknown"


def _activity_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(_parse_date_bucket(row.get("event_timestamp") or row.get("timestamp") or row.get("created_at")) for row in rows)
    return [{"date": date, "value": counts[date]} for date in sorted(counts)]


def _freshness_counts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = Counter(str(row.get("freshness") or "current") for row in facts)
    if not buckets:
        buckets["empty"] = 0
    return [{"name": name, "value": value} for name, value in buckets.items()]


def _aggregate_model_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    by_agent: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    totals = {
        "call_count": len(calls),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "local_call_count": 0,
        "cloud_call_count": 0,
    }
    for item in calls:
        prompt_tokens = int(item.get("prompt_tokens") or 0)
        completion_tokens = int(item.get("completion_tokens") or 0)
        total_tokens = int(item.get("total_tokens") or 0)
        estimated_cost = float(item.get("estimated_cost_usd") or 0.0)
        totals["prompt_tokens"] += prompt_tokens
        totals["completion_tokens"] += completion_tokens
        totals["total_tokens"] += total_tokens
        totals["estimated_cost_usd"] += estimated_cost
        is_local = bool(item.get("is_local"))
        totals["local_call_count" if is_local else "cloud_call_count"] += 1

        agent_key = str(item.get("agent_role") or item.get("agent_type") or "unknown")
        model_key = f"{item.get('provider') or 'unknown'}:{item.get('model_name') or 'unknown'}"
        for bucket, key in ((by_agent, agent_key), (by_model, model_key)):
            row = bucket.setdefault(
                key,
                {
                    "call_count": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                },
            )
            row["call_count"] += 1
            row["total_tokens"] += total_tokens
            row["estimated_cost_usd"] += estimated_cost

    totals["estimated_cost_usd"] = round(float(totals["estimated_cost_usd"]), 8)
    return {
        "totals": totals,
        "by_agent": [
            {"name": name, **{**row, "estimated_cost_usd": round(row["estimated_cost_usd"], 8)}}
            for name, row in sorted(by_agent.items())
        ],
        "by_model": [
            {"name": name, **{**row, "estimated_cost_usd": round(row["estimated_cost_usd"], 8)}}
            for name, row in sorted(by_model.items())
        ],
    }


def _recent_model_calls(calls: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    safe_keys = {
        "call_id",
        "created_at",
        "agent_role",
        "agent_type",
        "mode",
        "provider",
        "model_name",
        "is_local",
        "success",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "token_source",
        "estimated_cost_usd",
        "fallback_from",
        "fallback_to",
    }
    return [{key: value for key, value in item.items() if key in safe_keys} for item in calls[-limit:]]


def _event_write_paths(
    *,
    timeline: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    facts_by_source: dict[str, list[dict[str, Any]]] = {}
    history_by_source: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        source_id = str(fact.get("source_log_id") or "")
        if source_id:
            facts_by_source.setdefault(source_id, []).append(fact)
    for row in history:
        source_id = str(row.get("source_log_id") or row.get("new_source_log_id") or "")
        if source_id:
            history_by_source.setdefault(source_id, []).append(row)

    paths: list[dict[str, Any]] = []
    for event in timeline:
        event_id = str(event.get("id") or event.get("log_id") or "")
        linked_facts = facts_by_source.get(event_id, [])
        linked_history = history_by_source.get(event_id, [])
        status = "superseded" if event.get("superseded_at") else "active"
        hints: list[str] = []
        if status == "superseded":
            hints.append("event was superseded by a correction")
        if not linked_facts and not linked_history:
            hints.append("no source_log_id fact link found")
        paths.append(
            {
                "event_id": event_id,
                "thread_id": event.get("thread_id"),
                "role": event.get("role"),
                "status": status,
                "content": event.get("content"),
                "event_timestamp": event.get("event_timestamp") or event.get("created_at"),
                "linked_current_fact_count": len(linked_facts),
                "linked_history_count": len(linked_history),
                "risk_hints": hints,
                "linked_current_facts": linked_facts,
                "linked_history": linked_history,
            }
        )
    return paths


def quick_actions() -> list[dict[str, str]]:
    return [
        {"label": "Ask with Trace", "target": "#chat", "description": "Run a question through the audited pipeline."},
        {"label": "Recall Memory", "target": "#recall", "description": "Inspect facts-first retrieval and explanation."},
        {"label": "Add Fact", "target": "#facts", "description": "Create or update Entity Fact Sheet state."},
        {"label": "Review Timeline", "target": "#timeline", "description": "Browse events, corrections and snapshots."},
    ]


@router.get("/v1/ui/dashboard")
def ui_dashboard(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    validation = memory_service.validate_memory(scope_filters=scope)
    facts = memory_service.list_facts(scope_filters=scope)
    timeline = memory_service.recall_timeline(limit=250, scope_filters=scope)
    procedures = memory_service.list_procedures(scope_filters=scope)
    snapshots = memory_service.list_episodic_snapshots(scope_filters=scope)
    recent = timeline[:12]
    thread_counts = _count_by(timeline, "thread_id")
    category_counts = _count_by(facts, "category")
    merged_source_counts = source_counts([{**row, "_source": "entity_state"} for row in facts])
    merged_source_counts.update(source_counts([{**row, "_source": "memory_log"} for row in timeline]))
    data = {
        "kpis": {
            "facts": len(facts),
            "events": len(timeline),
            "procedures": len(procedures),
            "snapshots": len(snapshots),
            "threads": len({str(row.get("thread_id") or "") for row in timeline if row.get("thread_id")}),
        },
        "validation": validation,
        "charts": {
            "facts_by_category": category_counts,
            "events_by_role": _count_by(timeline, "role"),
            "events_by_thread": thread_counts[:8],
            "activity_by_day": _activity_series(timeline),
            "fact_freshness": _freshness_counts(facts),
            "source_counts": [{"name": key, "value": value} for key, value in merged_source_counts.items()],
        },
        "recent_activity": recent,
        "top_facts": facts[:10],
        "procedures": procedures[:8],
        "snapshots": snapshots[:8],
        "quick_actions": quick_actions(),
        "system_map": [
            {"name": "Router", "status": "configured", "description": "Classifies whether memory is needed."},
            {"name": "Notetaker", "status": "configured", "description": "Builds minimal fact sheets from recall."},
            {"name": "Planner", "status": "configured", "description": "Adds explicit reasoning plans when useful."},
            {"name": "Executor", "status": "configured", "description": "Answers from the supported context."},
        ],
    }
    return response_object("mase.ui.dashboard", data, {"scope": scope, "generated_at": int(time.time())})


@router.get("/v1/ui/observability")
def ui_observability(
    recent_limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    system = get_system(config_path=SERVER_CONFIG_PATH)
    metrics_snapshot = get_metrics().snapshot()
    model_calls = system.model_interface.get_call_log()
    pricing_catalog = load_pricing_catalog(config_path=SERVER_CONFIG_PATH)
    data = {
        "mode": {
            "read_only": is_read_only_mode(),
            "auth_required": read_internal_api_key() is not None,
            "frontend_static_ready": (FRONTEND_DIST / "index.html").exists(),
        },
        "models": describe_models(config_path=SERVER_CONFIG_PATH),
        "memory_validation": memory_service.validate_memory(),
        "metrics": {
            "event_counters": metrics_snapshot.get("event_counters", {}),
            "latency_ms_avg": metrics_snapshot.get("latency_ms_avg", {}),
        },
        "model_health": metrics_snapshot.get("candidate_health", []),
        "model_ledger": {
            **_aggregate_model_calls(model_calls),
            "recent_calls": _recent_model_calls(model_calls, recent_limit),
        },
        "cost_center": build_cost_center(model_calls, pricing_catalog, recent_limit=recent_limit),
    }
    return response_object("mase.ui.observability", data, {"generated_at": int(time.time())})


@router.get("/v1/ui/write-inspector")
def ui_write_inspector(
    thread_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    timeline = memory_service.recall_timeline(thread_id=thread_id, limit=limit, scope_filters=scope)
    facts = memory_service.list_facts(scope_filters=scope)
    history = memory_service.get_fact_history(limit=500, scope_filters=scope)
    paths = _event_write_paths(timeline=timeline, facts=facts, history=history)
    data = {
        "thread_id": thread_id,
        "write_paths": paths,
        "summary": {
            "event_count": len(timeline),
            "active_event_count": sum(1 for row in timeline if not row.get("superseded_at")),
            "superseded_event_count": sum(1 for row in timeline if row.get("superseded_at")),
            "linked_fact_count": sum(int(row["linked_current_fact_count"]) for row in paths),
            "unlinked_event_count": sum(1 for row in paths if "no source_log_id fact link found" in row["risk_hints"]),
        },
    }
    return response_object("mase.ui.write_inspector", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = [
    "quick_actions",
    "router",
    "ui_dashboard",
    "ui_observability",
    "ui_write_inspector",
]
