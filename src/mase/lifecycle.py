from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from mase_tools.memory.db_core import PROFILE_TEMPLATES

UTC = timezone.utc


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def classify_fact_lifecycle(fact: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now_value = now or datetime.now(UTC)
    expiry = _parse_datetime(fact.get("will_expire_at") or fact.get("expires_at"))
    ttl_days = fact.get("ttl_days")
    importance = float(fact.get("importance_score") or 0.5)
    archived = bool(fact.get("archived"))
    if archived:
        state = "archived"
    elif expiry and expiry <= now_value:
        state = "expired"
    elif expiry and expiry <= now_value + timedelta(days=7):
        state = "expiring_soon"
    elif ttl_days is None and importance >= 0.75:
        state = "long_term_fact"
    elif ttl_days is not None:
        state = "working_memory"
    else:
        state = "stable_fact"
    return {
        "state": state,
        "importance_score": importance,
        "ttl_days": ttl_days,
        "expires_at": expiry.isoformat() if expiry else None,
        "promotion_candidate": state == "stable_fact" and importance >= 0.65,
        "archive_candidate": state in {"expired", "archived"} or importance < 0.2,
    }


def validate_fact_contract(fact: dict[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for field in ("category", "entity_key", "entity_value"):
        if not str(fact.get(field) or "").strip():
            violations.append({"field": field, "severity": "error", "message": f"missing {field}"})
    category = str(fact.get("category") or "").strip()
    if category and category not in PROFILE_TEMPLATES:
        violations.append({"field": "category", "severity": "warning", "message": "category is not in profile templates"})
    importance = fact.get("importance_score")
    if importance is not None and not 0 <= float(importance) <= 1:
        violations.append({"field": "importance_score", "severity": "error", "message": "importance_score must be 0..1"})
    ttl_days = fact.get("ttl_days")
    if ttl_days is not None and int(ttl_days) < 0:
        violations.append({"field": "ttl_days", "severity": "error", "message": "ttl_days must be non-negative"})
    return violations


def build_lifecycle_report(facts: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_state: dict[str, int] = {}
    violation_count = 0
    for fact in facts:
        lifecycle = classify_fact_lifecycle(fact, now=now)
        violations = validate_fact_contract(fact)
        by_state[lifecycle["state"]] = by_state.get(lifecycle["state"], 0) + 1
        violation_count += len(violations)
        rows.append(
            {
                "category": fact.get("category"),
                "entity_key": fact.get("entity_key"),
                "entity_value": fact.get("entity_value"),
                "updated_at": fact.get("updated_at"),
                "source_log_id": fact.get("source_log_id"),
                "tenant_id": fact.get("tenant_id"),
                "workspace_id": fact.get("workspace_id"),
                "visibility": fact.get("visibility"),
                "lifecycle": lifecycle,
                "contract_violations": violations,
            }
        )
    return {
        "summary": {
            "fact_count": len(facts),
            "by_state": by_state,
            "contract_violation_count": violation_count,
            "profile_template_count": len(PROFILE_TEMPLATES),
        },
        "facts": rows,
        "contract": {
            "required_fields": ["category", "entity_key", "entity_value"],
            "known_categories": sorted(PROFILE_TEMPLATES),
            "importance_score_range": [0, 1],
        },
    }


__all__ = ["build_lifecycle_report", "classify_fact_lifecycle", "validate_fact_contract"]
