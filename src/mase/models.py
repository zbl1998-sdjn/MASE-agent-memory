"""Public dataclasses describing one MASE orchestration trace.

Lives in its own module so consumers can `from mase.models import ...`
without triggering the heavyweight `engine` import (which loads the model
interface, agents and SQLite layer).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .topic_threads import ThreadContext


@dataclass(frozen=True)
class RouteDecision:
    action: str
    keywords: list[str]


@dataclass(frozen=True)
class PlannerSnapshot:
    text: str
    source: str = "model"

    def to_dict(self) -> dict[str, Any]:
        return {"plan_text": self.text, "source": self.source}


@dataclass(frozen=True)
class OrchestrationTrace:
    route: RouteDecision
    planner: PlannerSnapshot
    thread: ThreadContext
    executor_target: dict[str, Any]
    answer: str
    search_results: list[dict[str, Any]]
    fact_sheet: str
    evidence_assessment: dict[str, Any] | None = None
    record_path: str = ""
    trace_id: str = ""
    steps: list[dict[str, Any]] | None = None


__all__ = ["RouteDecision", "PlannerSnapshot", "OrchestrationTrace"]
