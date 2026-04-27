from __future__ import annotations

from typing import Any


def evaluate_memory_case(
    *,
    expected: str,
    actual: str,
    trace: dict[str, Any] | None = None,
    problem_type: str = "general",
) -> dict[str, Any]:
    expected_text = str(expected or "").strip()
    actual_text = str(actual or "").strip()
    trace_data = trace or {}
    search_results = trace_data.get("search_results") or []
    freshness = [str(item.get("freshness") or "") for item in search_results if isinstance(item, dict)]
    sources = [str(item.get("_source") or "") for item in search_results if isinstance(item, dict)]
    return {
        "hit": expected_text.lower() in actual_text.lower() if expected_text else bool(actual_text),
        "problem_type": problem_type,
        "current_state_hit": problem_type == "current_state" and expected_text.lower() in actual_text.lower(),
        "temporal_hit": problem_type == "temporal" and expected_text.lower() in actual_text.lower(),
        "correction_hit": any(source == "entity_state_history" for source in sources),
        "stale_suppressed": "stale" not in freshness[:1],
        "multipass_recovered": bool(trace_data.get("evidence_assessment", {}).get("retrieval_plan", {}).get("use_multipass")),
        "provenance_depth": len(search_results),
    }


__all__ = ["evaluate_memory_case"]
