from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc


def _incident(kind: str, severity: str, title: str, source: str, evidence: dict[str, Any]) -> dict[str, Any]:
    raw = f"{kind}:{severity}:{title}:{source}:{evidence}".encode("utf-8", errors="ignore")
    return {
        "incident_id": f"inc_{hashlib.sha1(raw).hexdigest()[:12]}",
        "kind": kind,
        "severity": severity,
        "title": title,
        "source": source,
        "status": "open",
        "created_at": datetime.now(UTC).isoformat(),
        "evidence": evidence,
    }


def build_memory_incidents(
    *,
    drift_report: dict[str, Any],
    slo_report: dict[str, Any],
) -> dict[str, Any]:
    incidents: list[dict[str, Any]] = []
    for issue in drift_report.get("issues", []):
        if issue.get("severity") == "high":
            incidents.append(
                _incident(
                    "memory_drift",
                    "high",
                    str(issue.get("message") or "High severity memory drift"),
                    "drift-detector",
                    issue,
                )
            )

    for objective in slo_report.get("objectives", []):
        if objective.get("status") == "breached":
            incidents.append(
                _incident(
                    "slo_breach",
                    "critical" if objective.get("name") == "critical_regression_free" else "high",
                    f"SLO breached: {objective.get('name')}",
                    "slo-dashboard",
                    objective,
                )
            )

    by_severity: dict[str, int] = {}
    for incident in incidents:
        severity = str(incident["severity"])
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {
        "summary": {
            "incident_count": len(incidents),
            "by_severity": by_severity,
            "status": "open_incidents" if incidents else "clean",
        },
        "incidents": incidents,
    }


__all__ = ["build_memory_incidents"]
