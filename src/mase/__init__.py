"""MASE - Multi-Agent System Evolution 的公共门面。

真实逻辑都放在专门模块中，后续 math/code/multimodal agent 接入时
不需要继续膨胀这个门面文件。

兼容性约束：这里重新导出的名称过去都能直接从 `mase` 导入，
benchmark runner 和外部脚本依赖这个表面保持稳定。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .benchmark_notetaker import BenchmarkNotetaker, get_notetaker
from .engine import MASESystem, get_system, reload_system
from .memory_service import MemoryService
from .models import OrchestrationTrace, PlannerSnapshot, RouteDecision
from .router import ROUTER_SYSTEM


def describe_models(config_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """通过全局系统实例读取当前模型配置摘要。"""
    return get_system(config_path=config_path).describe_models()


def call_router(
    user_question: str,
    system_prompt: str = ROUTER_SYSTEM,
    apply_heuristic: bool = True,
) -> dict[str, Any]:
    """兼容旧入口的 router 调用包装。"""
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
    """兼容旧入口的 router 探针；默认不套启发式。"""
    return get_system().probe_router(
        user_question=user_question,
        system_prompt=system_prompt,
        apply_heuristic=apply_heuristic,
    )


def call_notetaker_with_tools(user_message: str, context: str = "") -> dict[str, Any]:
    """测试/兼容用轻量 notetaker stub，不触发真实工具写入。"""
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
    """兼容旧入口的 executor 调用包装。"""
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
    """兼容旧入口的交互摘要包装。"""
    return get_system().summarize_interaction(user_question, assistant_response)


def mase_run(user_question: str, log: bool = True) -> OrchestrationTrace:
    """执行完整编排并返回 trace。"""
    return get_system().run_with_trace(user_question, log=log)


def mase_ask(user_question: str, log: bool = True) -> str:
    """执行完整编排并只返回最终回答。"""
    return get_system().ask(user_question, log=log)


__all__ = [
    "MASESystem",
    "BenchmarkNotetaker",
    "MemoryService",
    "get_notetaker",
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
