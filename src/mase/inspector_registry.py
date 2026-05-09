from __future__ import annotations

from typing import Any

BUILTIN_INSPECTORS: list[dict[str, Any]] = [
    {
        "id": "drift-detector",
        "name": "Memory Drift Detector",
        "kind": "governance",
        "status": "enabled",
        "signals": ["conflicting_fact_values", "duplicate_fact_value", "stale_memory_pressure"],
    },
    {
        "id": "slo-dashboard",
        "name": "Memory SLO Dashboard",
        "kind": "reliability",
        "status": "enabled",
        "signals": ["golden_pass_rate", "critical_regression_free", "cost_pricing_coverage"],
    },
    {
        "id": "refusal-quality",
        "name": "Refusal Quality",
        "kind": "answer_quality",
        "status": "enabled",
        "signals": ["over_refusal", "unsupported_answer"],
    },
]


def list_inspectors() -> dict[str, Any]:
    return {
        "summary": {
            "inspector_count": len(BUILTIN_INSPECTORS),
            "enabled_count": sum(1 for inspector in BUILTIN_INSPECTORS if inspector["status"] == "enabled"),
        },
        "inspectors": BUILTIN_INSPECTORS,
    }


__all__ = ["BUILTIN_INSPECTORS", "list_inspectors"]
