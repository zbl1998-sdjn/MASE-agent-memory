from __future__ import annotations

from mase.slo_dashboard import build_slo_dashboard


def test_slo_dashboard_marks_met_when_sources_are_healthy() -> None:
    report = build_slo_dashboard(
        golden_report={"summary": {"pass_rate": 1.0, "critical_failed_count": 0, "release_gate": "passed"}},
        lifecycle_report={"summary": {"fact_count": 10, "contract_violation_count": 0}},
        cost_report={"pricing_coverage": {"coverage_ratio": 1.0, "unpriced_call_count": 0}},
    )

    assert report["summary"]["overall_status"] == "met"
    assert report["summary"]["breached_count"] == 0


def test_slo_dashboard_breaches_on_critical_regression() -> None:
    report = build_slo_dashboard(
        golden_report={"summary": {"pass_rate": 0.5, "critical_failed_count": 1, "release_gate": "blocked"}},
        lifecycle_report={"summary": {"fact_count": 2, "contract_violation_count": 1}},
        cost_report={"pricing_coverage": {"coverage_ratio": 0.5, "unpriced_call_count": 1}},
    )

    assert report["summary"]["overall_status"] == "breached"
    assert report["summary"]["release_gate"] == "blocked"
    assert any(item["name"] == "critical_regression_free" for item in report["objectives"])
