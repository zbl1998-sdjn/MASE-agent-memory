from __future__ import annotations

from typing import Any


def _ratio(value: Any, default: float = 1.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _objective(name: str, value: float, target: float, *, source: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    if value >= target:
        status = "met"
    elif value >= target * 0.9:
        status = "warning"
    else:
        status = "breached"
    return {
        "name": name,
        "value": round(value, 3),
        "target": target,
        "status": status,
        "source": source,
        "details": details or {},
    }


def build_slo_dashboard(
    *,
    golden_report: dict[str, Any],
    lifecycle_report: dict[str, Any],
    cost_report: dict[str, Any],
) -> dict[str, Any]:
    golden_summary = golden_report.get("summary", {})
    lifecycle_summary = lifecycle_report.get("summary", {})
    cost_coverage = cost_report.get("pricing_coverage", {})

    fact_count = int(lifecycle_summary.get("fact_count") or 0)
    violation_count = int(lifecycle_summary.get("contract_violation_count") or 0)
    contract_score = 1.0 if fact_count == 0 else max(0.0, 1.0 - (violation_count / max(1, fact_count)))
    release_gate = str(golden_summary.get("release_gate") or "unknown")

    objectives = [
        _objective(
            "golden_pass_rate",
            _ratio(golden_summary.get("pass_rate")),
            0.95,
            source="golden_tests",
            details={"release_gate": release_gate},
        ),
        _objective(
            "critical_regression_free",
            0.0 if int(golden_summary.get("critical_failed_count") or 0) else 1.0,
            1.0,
            source="golden_tests",
            details={"critical_failed_count": golden_summary.get("critical_failed_count", 0)},
        ),
        _objective(
            "memory_contract_health",
            contract_score,
            0.98,
            source="lifecycle_contracts",
            details={"fact_count": fact_count, "contract_violation_count": violation_count},
        ),
        _objective(
            "cost_pricing_coverage",
            _ratio(cost_coverage.get("coverage_ratio")),
            0.99,
            source="cost_center",
            details={"unpriced_call_count": cost_coverage.get("unpriced_call_count", 0)},
        ),
    ]
    breached = [objective for objective in objectives if objective["status"] == "breached"]
    warnings = [objective for objective in objectives if objective["status"] == "warning"]
    return {
        "summary": {
            "objective_count": len(objectives),
            "met_count": sum(1 for objective in objectives if objective["status"] == "met"),
            "warning_count": len(warnings),
            "breached_count": len(breached),
            "overall_status": "breached" if breached else ("warning" if warnings else "met"),
            "release_gate": release_gate,
        },
        "objectives": objectives,
        "source_reports": {
            "golden": golden_summary,
            "lifecycle": lifecycle_summary,
            "cost": cost_coverage,
        },
    }


__all__ = ["build_slo_dashboard"]
