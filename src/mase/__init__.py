"""MASE — Multi-Agent System Evolution.

Public façade.  All real logic lives in dedicated modules so future agents
(math, code, multimodal) can plug in without touching this file.

Backwards-compat: every name re-exported here was previously importable
from `mase` directly; benchmark runners and external scripts depend on
that surface staying stable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .benchmark_notetaker import BenchmarkNotetaker
from .engine import MASESystem, get_system, reload_system
from .models import OrchestrationTrace, PlannerSnapshot, RouteDecision
from .router import ROUTER_SYSTEM


def describe_models(config_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    return get_system(config_path=config_path).describe_models()


def call_router(
    user_question: str,
    system_prompt: str = ROUTER_SYSTEM,
    apply_heuristic: bool = True,
) -> dict[str, Any]:
    return get_system().call_router(
        user_question=user_question,
        system_prompt=system_prompt,
        apply_heuristic=apply_heuristic,
    )


def probe_router(
    user_question: str,
    system_prompt: str = ROUTER_SYSTEM,
    apply_heuristic: bool = False,
) -> dict[str, Any]:
    return get_system().probe_router(
        user_question=user_question,
        system_prompt=system_prompt,
        apply_heuristic=apply_heuristic,
    )


def call_notetaker_with_tools(user_message: str, context: str = "") -> dict[str, Any]:
    summary = (context.strip() + "\n" + user_message.strip()).strip()
    return {"final_response": summary, "tool_results": []}


def call_executor(
    user_question: str,
    fact_sheet: str,
    allow_general_knowledge: bool = False,
    task_type: str | None = None,
    use_memory: bool | None = None,
    memory_heat: str | None = None,
    executor_role: str | None = None,
    collaboration_mode: str | None = None,
    instruction_package: str = "",
) -> str:
    return get_system().call_executor(
        user_question=user_question,
        fact_sheet=fact_sheet,
        allow_general_knowledge=allow_general_knowledge,
        task_type=task_type,
        use_memory=use_memory,
        memory_heat=memory_heat,
        executor_role=executor_role,
        collaboration_mode=collaboration_mode,
        instruction_package=instruction_package,
    )


def summarize_interaction(user_question: str, assistant_response: str) -> str:
    return get_system().summarize_interaction(user_question, assistant_response)


def mase_run(user_question: str, log: bool = True) -> OrchestrationTrace:
    return get_system().run_with_trace(user_question, log=log)


def mase_ask(user_question: str, log: bool = True) -> str:
    return get_system().ask(user_question, log=log)


__all__ = [
    "MASESystem",
    "BenchmarkNotetaker",
    "OrchestrationTrace",
    "RouteDecision",
    "PlannerSnapshot",
    "get_system",
    "reload_system",
    "describe_models",
    "call_router",
    "probe_router",
    "call_notetaker_with_tools",
    "call_executor",
    "summarize_interaction",
    "mase_run",
    "mase_ask",
]
