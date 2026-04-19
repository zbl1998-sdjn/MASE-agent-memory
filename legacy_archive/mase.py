from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

from executor import ExecutorAgent
from model_interface import ModelInterface, resolve_config_path
from notetaker_agent import NOTETAKER_SYSTEM, NOTETAKER_TOOLS, NotetakerAgent
from orchestrator import MASEOrchestrator, OrchestrationTrace
from planner_agent import PlannerAgent
from router import ROUTER_SYSTEM, RouterAgent, parse_router_response

MASE_VERSION = "v0.4-configurable-hotswap"
TOOLS = NOTETAKER_TOOLS


def _contains_any(text: str, fragments: list[str]) -> bool:
    return any(fragment in text for fragment in fragments)


def _memory_result_limit(user_question: str) -> int | None:
    single_fact_markers = ["我刚才说", "是什么", "是多少", "哪天", "几号", "多少"]
    synthesis_markers = ["总结", "整理", "归纳", "对比", "方案", "复盘", "写"]
    aggregation_markers = [
        "how many",
        "how much",
        "how long",
        "in total",
        "combined",
        "altogether",
        "count",
        "sum",
        "total",
        "spent",
        "acquire",
        "acquired",
        "bake",
        "born",
        "furniture",
        "baby",
        "plants",
    ]

    if _contains_any(user_question, synthesis_markers):
        return None
    if _contains_any(user_question.lower(), aggregation_markers):
        return None
    if _contains_any(user_question, single_fact_markers):
        return 1
    return 3


def _extract_remember_payload(user_question: str) -> str | None:
    patterns = [
        r"^\s*请记住[:：]?\s*(.+?)\s*$",
        r"^\s*记住[:：]?\s*(.+?)\s*$",
        r"^\s*记一下[:：]?\s*(.+?)\s*$",
        r"^\s*帮我记住[:：]?\s*(.+?)\s*$",
        r"^\s*保存这个信息[:：]?\s*(.+?)\s*$",
    ]
    for pattern in patterns:
        match = re.match(pattern, user_question.strip())
        if match:
            payload = match.group(1).strip().rstrip("。！？!?,，")
            return payload or None
    return None


def _rule_based_summary(user_question: str, assistant_response: str) -> str | None:
    remember_payload = _extract_remember_payload(user_question)
    if remember_payload:
        return f"用户要求记住：{remember_payload}。"

    if assistant_response.strip().startswith("我未找到相关记录"):
        return f"用户询问：{user_question.strip()}；系统未找到相关记录。"

    return None


class MASESystem:
    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = resolve_config_path(config_path)
        os.environ["MASE_CONFIG_PATH"] = str(self.config_path)
        self.model_interface = ModelInterface(self.config_path)
        self.router_agent = RouterAgent(self.model_interface)
        self.notetaker_agent = NotetakerAgent(self.model_interface)
        self.planner_agent = PlannerAgent(self.model_interface)
        self.executor_agent = ExecutorAgent(self.model_interface)
        self.orchestrator = MASEOrchestrator(
            router=self.call_router,
            executor=self.call_executor,
            summarizer=self.summarize_interaction,
            notetaker=self.notetaker_agent,
            memory_result_limit=_memory_result_limit,
            executor_target_resolver=self.describe_executor_target,
            planner_agent=self.planner_agent,
        )

    def reload(self) -> None:
        os.environ["MASE_CONFIG_PATH"] = str(self.config_path)
        self.model_interface.reload()

    def describe_models(self) -> dict[str, dict[str, Any]]:
        return {
            agent_type: self.model_interface.describe_agent(agent_type)
            for agent_type in ("router", "notetaker", "planner", "executor")
        }

    def describe_executor_target(
        self,
        mode: str,
        user_question: str,
        use_memory: bool,
        memory_heat: str | None = None,
        executor_role: str | None = None,
    ) -> dict[str, Any]:
        return self.executor_agent.describe_target(
            mode=mode,
            user_question=user_question,
            use_memory=use_memory,
            memory_heat=memory_heat,
            executor_role=executor_role,
        )

    def call_router(
        self,
        user_question: str,
        system_prompt: str | None = None,
        apply_heuristic: bool = True,
    ) -> dict[str, Any]:
        return self.router_agent.decide(
            user_question=user_question,
            system_prompt=system_prompt,
            apply_heuristic=apply_heuristic,
        )

    def probe_router(
        self,
        user_question: str,
        system_prompt: str | None = None,
        apply_heuristic: bool = False,
    ) -> dict[str, Any]:
        return self.router_agent.probe(
            user_question=user_question,
            system_prompt=system_prompt,
            apply_heuristic=apply_heuristic,
        )

    def call_notetaker_with_tools(self, user_message: str, context: str = "") -> dict[str, Any]:
        return self.notetaker_agent.chat_with_tools(user_message=user_message, context=context)

    def _resolve_executor_task_type(
        self,
        task_type: str | None,
        use_memory: bool,
        allow_general_knowledge: bool,
    ) -> str:
        if task_type:
            return task_type
        if use_memory and not allow_general_knowledge:
            return "grounded_answer"
        return "general_answer"

    def call_executor(
        self,
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
        effective_use_memory = (not allow_general_knowledge) if use_memory is None else use_memory
        effective_task_type = self._resolve_executor_task_type(
            task_type=task_type,
            use_memory=effective_use_memory,
            allow_general_knowledge=allow_general_knowledge,
        )
        mode = effective_task_type if effective_task_type else "general_answer"
        return self.executor_agent.execute(
            mode=mode,
            user_question=user_question,
            context=fact_sheet,
            use_memory=effective_use_memory,
            memory_heat=memory_heat,
            executor_role=executor_role,
            collaboration_mode=collaboration_mode,
            instruction_package=instruction_package,
        )

    def summarize_interaction(self, user_question: str, assistant_response: str) -> str:
        rule_summary = _rule_based_summary(user_question, assistant_response)
        if rule_summary is not None:
            return rule_summary[:30]
        summary = self.notetaker_agent.generate_summary(user_question, assistant_response)
        return summary[:30]

    def run_with_trace(
        self,
        user_question: str,
        log: bool = True,
        forced_route: dict[str, Any] | None = None,
    ) -> OrchestrationTrace:
        return self.orchestrator.run_with_trace(user_question, log=log, forced_route=forced_route)

    def ask(self, user_question: str, log: bool = True) -> str:
        return self.orchestrator.run(user_question, log=log)


_SYSTEM_CACHE: dict[str, MASESystem] = {}
_SYSTEM_CACHE_LOCK = threading.Lock()


def get_system(config_path: str | Path | None = None, reload: bool = False) -> MASESystem:
    resolved_path = str(resolve_config_path(config_path))
    with _SYSTEM_CACHE_LOCK:
        system = _SYSTEM_CACHE.get(resolved_path)
        if system is None:
            system = MASESystem(resolved_path)
            _SYSTEM_CACHE[resolved_path] = system
        elif reload:
            system.reload()
    return system


def reload_system(config_path: str | Path | None = None) -> MASESystem:
    resolved_path = str(resolve_config_path(config_path))
    with _SYSTEM_CACHE_LOCK:
        system = MASESystem(resolved_path)
        _SYSTEM_CACHE[resolved_path] = system
    return system


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
    return get_system().call_notetaker_with_tools(user_message=user_message, context=context)


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


def interactive_cli(config_path: str | Path | None = None) -> None:
    system = get_system(config_path=config_path)
    print("MASE Demo 已启动，输入 exit 或 quit 退出。")
    while True:
        user_question = input("\n用户: ").strip()
        if user_question.lower() in {"exit", "quit"}:
            break

        answer = system.ask(user_question)
        print(f"助手: {answer}")


if __name__ == "__main__":
    interactive_cli()
