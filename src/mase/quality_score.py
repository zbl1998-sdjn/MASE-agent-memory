from __future__ import annotations

from typing import Any

from mase.lifecycle import classify_fact_lifecycle, validate_fact_contract
from mase.privacy import scan_value


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _grade(score: float) -> str:
    if score >= 0.85:
        return "excellent"
    if score >= 0.7:
        return "good"
    if score >= 0.5:
        return "watch"
    return "risk"


def score_fact(fact: dict[str, Any]) -> dict[str, Any]:
    lifecycle = classify_fact_lifecycle(fact)
    violations = validate_fact_contract(fact)
    privacy_findings = scan_value(fact)
    risk_flags: list[str] = []
    if violations:
        risk_flags.append("contract_violation")
    if privacy_findings:
        risk_flags.append("privacy_finding")
    if not fact.get("source_log_id"):
        risk_flags.append("missing_source_log_id")
    if lifecycle["state"] in {"expired", "archived", "expiring_soon"}:
        risk_flags.append(f"lifecycle:{lifecycle['state']}")
    components = {
        "contract": 1.0 if not violations else 0.6,
        "provenance": 1.0 if fact.get("source_log_id") else 0.35,
        "freshness": 0.45 if lifecycle["state"] == "expired" else 0.7 if lifecycle["state"] == "expiring_soon" else 1.0,
        "privacy": 1.0 if not privacy_findings else 0.1,
        "scope": 1.0 if fact.get("tenant_id") or fact.get("workspace_id") else 0.75,
    }
    score = _bounded(sum(components.values()) / len(components))
    return {
        "target_type": "fact",
        "target_id": f"{fact.get('category')}.{fact.get('entity_key')}",
        "score": score,
        "grade": _grade(score),
        "components": components,
        "risk_flags": risk_flags,
        "lifecycle": lifecycle,
    }


def score_recall_hit(hit: dict[str, Any]) -> dict[str, Any]:
    risk_flags: list[str] = []
    source = str(hit.get("_source") or hit.get("source") or "unknown")
    if hit.get("superseded_at"):
        risk_flags.append("superseded")
    if hit.get("conflict_status") not in (None, "", "none", "stable", "resolved"):
        risk_flags.append(f"conflict:{hit.get('conflict_status')}")
    if scan_value(hit):
        risk_flags.append("privacy_finding")
    components = {
        "source": 1.0 if source == "entity_state" else 0.65,
        "freshness": 0.2 if hit.get("superseded_at") else 1.0,
        "support": 1.0 if hit.get("entity_value") or hit.get("content") else 0.4,
        "conflict": 0.5 if any(flag.startswith("conflict:") for flag in risk_flags) else 1.0,
        "privacy": 0.25 if "privacy_finding" in risk_flags else 1.0,
    }
    score = _bounded(sum(components.values()) / len(components))
    return {
        "target_type": "recall_hit",
        "target_id": str(hit.get("id") or hit.get("source_log_id") or hit.get("entity_key") or "unknown"),
        "score": score,
        "grade": _grade(score),
        "components": components,
        "risk_flags": risk_flags,
    }


def score_trace_summary(summary: dict[str, Any]) -> dict[str, Any]:
    risk_flags = [str(item) for item in summary.get("risk_flags") or []]
    total_tokens = int(summary.get("total_tokens") or 0)
    estimated_cost = float(summary.get("estimated_cost_usd") or 0.0)
    components = {
        "risk": 1.0 if not risk_flags else 0.3,
        "answer": 1.0 if summary.get("answer_preview") else 0.6,
        "cost": 0.6 if estimated_cost > 0.05 or total_tokens > 20000 else 1.0,
        "cloud": 0.8 if summary.get("has_cloud_call") else 1.0,
    }
    score = _bounded(sum(components.values()) / len(components))
    return {
        "target_type": "trace",
        "target_id": str(summary.get("trace_id") or "unknown"),
        "score": score,
        "grade": _grade(score),
        "components": components,
        "risk_flags": risk_flags,
    }


def build_quality_report(
    *,
    facts: list[dict[str, Any]],
    recall_hits: list[dict[str, Any]] | None = None,
    trace_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = [
        *(score_fact(fact) for fact in facts),
        *(score_recall_hit(hit) for hit in (recall_hits or [])),
        *(score_trace_summary(summary) for summary in (trace_summaries or [])),
    ]
    average = _bounded(sum(item["score"] for item in items) / len(items)) if items else 1.0
    return {
        "summary": {
            "item_count": len(items),
            "average_score": average,
            "grade": _grade(average),
            "risk_count": sum(1 for item in items if item["risk_flags"]),
        },
        "items": sorted(items, key=lambda item: item["score"]),
    }


__all__ = ["build_quality_report", "score_fact", "score_recall_hit", "score_trace_summary"]
