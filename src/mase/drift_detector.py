from __future__ import annotations

from collections import defaultdict
from typing import Any

from mase.lifecycle import classify_fact_lifecycle


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _fingerprint(fact: dict[str, Any]) -> tuple[str, str]:
    return (_norm(fact.get("category")), _norm(fact.get("entity_key")))


def _value(fact: dict[str, Any]) -> str:
    return _norm(fact.get("entity_value"))


def _issue(kind: str, severity: str, message: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "message": message,
        "fact_count": len(facts),
        "facts": facts[:10],
    }


def detect_memory_drift(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_value: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    issues: list[dict[str, Any]] = []
    for fact in facts:
        by_key[_fingerprint(fact)].append(fact)
        by_value[(_norm(fact.get("category")), _value(fact))].append(fact)

    for (category, entity_key), rows in by_key.items():
        values = {_value(row) for row in rows if _value(row)}
        if category and entity_key and len(values) > 1:
            issues.append(
                _issue(
                    "conflicting_fact_values",
                    "high",
                    f"{category}/{entity_key} has {len(values)} active values",
                    rows,
                )
            )

    for (category, value), rows in by_value.items():
        keys = {_norm(row.get("entity_key")) for row in rows if _norm(row.get("entity_key"))}
        if category and value and len(keys) > 1:
            issues.append(
                _issue(
                    "duplicate_fact_value",
                    "medium",
                    f"{category} repeats the same value across {len(keys)} keys",
                    rows,
                )
            )

    lifecycle_rows = [{"fact": fact, "lifecycle": classify_fact_lifecycle(fact)} for fact in facts]
    stale_rows = [row["fact"] for row in lifecycle_rows if row["lifecycle"]["state"] in {"expired", "expiring_soon"}]
    if stale_rows:
        issues.append(
            _issue(
                "stale_memory_pressure",
                "medium",
                f"{len(stale_rows)} facts are expired or expiring soon",
                stale_rows,
            )
        )

    high_count = sum(1 for issue in issues if issue["severity"] == "high")
    medium_count = sum(1 for issue in issues if issue["severity"] == "medium")
    return {
        "summary": {
            "fact_count": len(facts),
            "issue_count": len(issues),
            "high_count": high_count,
            "medium_count": medium_count,
            "status": "attention_required" if high_count else ("watch" if medium_count else "clean"),
        },
        "issues": issues,
    }


__all__ = ["detect_memory_drift"]
