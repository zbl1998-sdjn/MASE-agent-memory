from __future__ import annotations

from typing import Any


def _percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def calculate_memory_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    total = len(rows)
    stale_hit = 0
    correction_hit = 0
    temporal_hit = 0
    current_state_hit = 0
    multipass_recovery = 0
    provenance_depth_total = 0
    latencies: list[float] = []

    for row in rows:
        hit = bool(row.get("hit"))
        if row.get("stale_suppressed"):
            stale_hit += 1
        if row.get("correction_hit"):
            correction_hit += 1
        if row.get("temporal_hit"):
            temporal_hit += 1
        if row.get("current_state_hit"):
            current_state_hit += 1
        if row.get("multipass_recovered"):
            multipass_recovery += 1
        provenance_depth_total += int(row.get("provenance_depth") or 0)
        if row.get("latency_ms") is not None:
            latencies.append(float(row["latency_ms"]))
        if hit and row.get("problem_type") == "current_state":
            current_state_hit += 0

    latencies.sort()
    if latencies:
        index = max(0, int(round(0.95 * (len(latencies) - 1))))
        latency_p95 = latencies[index]
    else:
        latency_p95 = 0.0

    return {
        "stale-hit": _percent(stale_hit, total),
        "correction-hit@k": _percent(correction_hit, total),
        "temporal-hit": _percent(temporal_hit, total),
        "current-state-hit": _percent(current_state_hit, total),
        "multipass-recovery": _percent(multipass_recovery, total),
        "latency-p95": latency_p95,
        "provenance-depth": (provenance_depth_total / total) if total else 0.0,
    }


__all__ = ["calculate_memory_metrics"]
