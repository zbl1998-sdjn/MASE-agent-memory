from __future__ import annotations

from mase.incidents import build_memory_incidents
from mase.inspector_registry import list_inspectors


def test_inspector_registry_lists_builtin_inspectors() -> None:
    report = list_inspectors()

    assert report["summary"]["enabled_count"] >= 3
    assert {item["id"] for item in report["inspectors"]} >= {"drift-detector", "slo-dashboard"}


def test_incidents_promote_drift_and_slo_breaches() -> None:
    report = build_memory_incidents(
        drift_report={
            "issues": [
                {
                    "kind": "conflicting_fact_values",
                    "severity": "high",
                    "message": "project/owner has two values",
                }
            ]
        },
        slo_report={"objectives": [{"name": "critical_regression_free", "status": "breached"}]},
    )

    assert report["summary"]["incident_count"] == 2
    assert report["summary"]["by_severity"]["critical"] == 1
