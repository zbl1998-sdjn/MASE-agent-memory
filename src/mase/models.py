"""描述一次 MASE 编排轨迹的公开 dataclass。

这些轻量类型放在独立模块中，调用方可以 ``from mase.models import ...``，
而不会触发重量级 ``engine`` 导入（engine 会加载模型接口、Agent 与 SQLite 层）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .topic_threads import ThreadContext


@dataclass(frozen=True)
class RouteDecision:
    """Router 的最小决策结果。"""

    action: str
    keywords: list[str]


@dataclass(frozen=True)
class PlannerSnapshot:
    """Planner 输出的可审计快照。"""

    text: str
    source: str = "model"

    def to_dict(self) -> dict[str, Any]:
        return {"plan_text": self.text, "source": self.source}


@dataclass(frozen=True)
class OrchestrationTrace:
    """一次端到端编排的核心轨迹。"""

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
