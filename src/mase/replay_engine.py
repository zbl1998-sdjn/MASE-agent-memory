from __future__ import annotations

from pathlib import Path
from typing import Any

from .metric_calculator import calculate_memory_metrics
from .trace_recorder import load_recorded_traces


def replay_trace_file(path: str | Path) -> dict[str, Any]:
    rows = load_recorded_traces(path)
    return {
        "count": len(rows),
        "rows": rows,
        "metrics": calculate_memory_metrics(
            [
                {
                    "latency_ms": row.get("evidence_assessment", {}).get("latency_ms", 0),
                    "provenance_depth": len(row.get("search_results") or []),
                    "stale_suppressed": True,
                    "correction_hit": any(
                        item.get("_source") == "entity_state_history" for item in (row.get("search_results") or [])
                    ),
                    "temporal_hit": False,
                    "current_state_hit": any(
                        item.get("_source") == "entity_state" for item in (row.get("search_results") or [])
                    ),
                    "multipass_recovered": bool(
                        row.get("evidence_assessment", {}).get("retrieval_plan", {}).get("use_multipass")
                    ),
                }
                for row in rows
            ]
        ),
    }


__all__ = ["replay_trace_file"]
