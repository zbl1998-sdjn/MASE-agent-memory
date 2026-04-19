"""
langgraph_orchestrator.py - MASE LangGraph orchestration (real agents wired).

V2.x audit (2026-04) found the previous implementation was a hardcoded mock:
- router_node ran keyword regex instead of RouterAgent.decide
- notetaker_node bypassed chat_with_tools and dumped the raw query as keywords
- planner_node was constructed without ModelInterface → fallback string
- action_node had a hardcoded ``if "时间" in query`` branch instead of
  exposing mase_tools.mcp.tools.TOOL_REGISTRY as Function-Calling schemas.

This rewrite wires every node to the real LLM agents while keeping the keyword
fast-path available behind ``MASE_ORCHESTRATOR_FAST=1`` for benchmarks that
intentionally want the cheap path. It also keeps the existing function names
and ``AgentState`` keys so any downstream graphs continue to compile.
"""
from __future__ import annotations

import json
import operator
import os
from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError as err:
    raise ImportError(
        "langgraph_orchestrator requires the 'langgraph' package. "
        "Install it with: pip install langgraph"
    ) from err

from .executor import ExecutorAgent
from .model_interface import ModelInterface
from .notetaker_agent import DEFAULT_NOTETAKER, NotetakerAgent
from .planner_agent import PlannerAgent
from .router import MEMORY_TRIGGER_PHRASES, RouterAgent, keyword_router_decision  # noqa: F401  (re-export)


class AgentState(TypedDict):
    messages: Annotated[Sequence[dict[str, Any]], operator.add]
    user_query: str
    router_decision: str
    memory_context: str
    task_plan: str
    action_results: str
    executor_result: str
    error_log: list[str]


# ---------------------------------------------------------------------------
# Lazy singletons: instantiated on first use so ``import mase`` stays cheap
# and CI / docs builds without a configured model don't crash on import.
# ---------------------------------------------------------------------------
mase_model_interface: ModelInterface | None = None
executor_agent: ExecutorAgent | None = None
_router_agent: RouterAgent | None = None
_notetaker_agent: NotetakerAgent | None = None
_planner_agent: PlannerAgent | None = None


def _get_model_interface() -> ModelInterface:
    global mase_model_interface
    if mase_model_interface is None:
        mase_model_interface = ModelInterface()
    return mase_model_interface


def _ensure_executor() -> ExecutorAgent:
    global executor_agent
    if executor_agent is None:
        executor_agent = ExecutorAgent(_get_model_interface())
    return executor_agent


def _get_router_agent() -> RouterAgent:
    global _router_agent
    if _router_agent is None:
        _router_agent = RouterAgent(_get_model_interface())
    return _router_agent


def _get_notetaker_agent() -> NotetakerAgent:
    """Use a model-backed notetaker so chat_with_tools() can run.

    DEFAULT_NOTETAKER is left without a model interface at import time so
    importing the module is free of side-effects; we upgrade it lazily here.
    """
    global _notetaker_agent
    if _notetaker_agent is None:
        # Reuse DEFAULT_NOTETAKER's tool handlers but attach a model_interface.
        DEFAULT_NOTETAKER.model_interface = _get_model_interface()
        _notetaker_agent = DEFAULT_NOTETAKER
    return _notetaker_agent


def _get_planner_agent() -> PlannerAgent:
    global _planner_agent
    if _planner_agent is None:
        _planner_agent = PlannerAgent(_get_model_interface())
    return _planner_agent


def _fast_path_enabled() -> bool:
    return os.environ.get("MASE_ORCHESTRATOR_FAST", "0").strip().lower() in {"1", "true", "on", "yes"}


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------
def router_node(state: AgentState):
    """Router Agent Node — calls RouterAgent.decide (real LLM) by default.

    Keyword fast-path is preserved as a fallback both for ``MASE_ORCHESTRATOR_FAST=1``
    and for any LLM failure (so a flaky model never hangs the graph).
    """
    query = state["user_query"]
    decision = "direct_answer"
    keywords: list[str] = []
    error: str | None = None

    if _fast_path_enabled():
        decision = keyword_router_decision(query)
    else:
        try:
            route = _get_router_agent().decide(user_question=query)
            decision = route.get("action") or "direct_answer"
            kw = route.get("keywords") or []
            if isinstance(kw, list):
                keywords = [str(x) for x in kw if str(x).strip()]
        except Exception as exc:  # noqa: BLE001
            error = f"router_llm_failed: {exc!r}"
            decision = keyword_router_decision(query)

    update: dict[str, Any] = {
        "router_decision": decision,
        "messages": [{"role": "system", "content": f"路由决策: {decision} (keywords={keywords})"}],
    }
    if keywords:
        update["memory_context"] = json.dumps({"_router_keywords": keywords}, ensure_ascii=False)
    if error:
        update["error_log"] = [error]
    return update


def _seed_keywords(state: AgentState, query: str) -> list[str]:
    raw = state.get("memory_context", "")
    if raw:
        try:
            parsed = json.loads(raw)
            kw = parsed.get("_router_keywords") if isinstance(parsed, dict) else None
            if isinstance(kw, list) and kw:
                return [str(x) for x in kw if str(x).strip()]
        except Exception:  # noqa: BLE001
            pass
    return [query]


def notetaker_node(state: AgentState):
    """Notetaker Agent Node — calls chat_with_tools() with NOTETAKER_TOOLS schema.

    The LLM decides which mase2_* tool to invoke and with which parameters; we
    then assemble the resulting records + entity facts into ``memory_context``.
    Falls back to direct execute_tool() on LLM failure so retrieval is never
    fully lost.
    """
    query = state["user_query"]
    notetaker = _get_notetaker_agent()
    keywords = _seed_keywords(state, query)
    memory_context = ""
    error_entries: list[str] = []

    used_llm = False
    if not _fast_path_enabled():
        try:
            outcome = notetaker.chat_with_tools(
                user_message=query,
                context=f"待检索关键词: {keywords}",
            )
            used_llm = True
            for executed in outcome.get("tool_results") or []:
                name = executed.get("name", "?")
                result = executed.get("result")
                if name == "mase2_search_memory" and isinstance(result, list):
                    for idx, item in enumerate(result):
                        memory_context += f"[{idx+1}] {item.get('content', '')}\n"
                elif name == "mase2_get_facts" and isinstance(result, list):
                    memory_context += "\n【核心实体状态】\n"
                    for fact in result:
                        memory_context += (
                            f"- {fact.get('category')}.{fact.get('key')}: {fact.get('value')}\n"
                        )
                else:
                    memory_context += f"\n[{name}] {result}\n"
            llm_summary = (outcome.get("final_response") or "").strip()
            if llm_summary:
                memory_context += f"\n【Notetaker 摘要】\n{llm_summary}\n"
        except Exception as exc:  # noqa: BLE001
            error_entries.append(f"notetaker_llm_failed: {exc!r}")
            used_llm = False

    if not used_llm:
        try:
            results = notetaker.execute_tool(
                "mase2_search_memory", {"keywords": keywords, "limit": 5}
            )
            for idx, item in enumerate(results or []):
                memory_context += f"[{idx+1}] {item.get('content', '')}\n"
            facts = notetaker.execute_tool("mase2_get_facts", {})
            if facts:
                memory_context += "\n【核心实体状态】\n"
                for fact in facts:
                    memory_context += (
                        f"- {fact.get('category')}.{fact.get('key')}: {fact.get('value')}\n"
                    )
        except Exception as exc:  # noqa: BLE001
            error_entries.append(f"notetaker_fallback_failed: {exc!r}")

    if not memory_context.strip():
        memory_context = "无相关记忆。"

    update: dict[str, Any] = {
        "memory_context": memory_context,
        "messages": [{"role": "system", "content": "已提取最新的 SQLite 记忆事实。"}],
    }
    if error_entries:
        update["error_log"] = error_entries
    return update


def planner_node(state: AgentState):
    """Planner Agent Node — uses model-backed PlannerAgent.

    The previous implementation used ``DEFAULT_PLANNER`` (no model_interface)
    which always fell back to a hardcoded plan string. We now route through
    the singleton planner created with the shared ModelInterface.
    """
    query = state.get("user_query", "")
    memory = state.get("memory_context", "")
    error: str | None = None
    try:
        plan = _get_planner_agent().plan(query=query, memory_context=memory)
    except Exception as exc:  # noqa: BLE001
        error = f"planner_llm_failed: {exc!r}"
        # Best-effort fallback so the graph still produces a non-empty plan.
        plan = "1. 结合查找到的记忆。\n2. 直接回答用户问题。"
    update: dict[str, Any] = {
        "task_plan": plan,
        "messages": [{"role": "system", "content": f"计划已生成: {plan}"}],
    }
    if error:
        update["error_log"] = [error]
    return update


def _build_mcp_tool_schemas() -> list[dict[str, Any]]:
    """Convert mase_tools.mcp.tools.TOOL_REGISTRY into OpenAI Function-Calling schemas."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "Return the current local system time as a string (YYYY-MM-DD HH:MM:SS).",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_local_file",
                "description": (
                    "Read a UTF-8 text file from the configured MCP sandbox. "
                    "Requires MASE_MCP_SANDBOX env var; otherwise returns a tagged error string."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Path relative to MASE_MCP_SANDBOX (or absolute inside it).",
                        }
                    },
                    "required": ["filepath"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List entries inside the MCP sandbox; directories end with '/'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dirpath": {
                            "type": "string",
                            "description": "Directory path relative to the sandbox (default '.').",
                        }
                    },
                    "required": [],
                },
            },
        },
    ]


def action_node(state: AgentState):
    """Action Node — exposes mase_tools.mcp.tools.TOOL_REGISTRY to the LLM.

    Replaces the hardcoded ``if "时间" in query`` branch with a single
    function-calling round: the LLM picks zero or more MCP tools and we
    execute them through the real sandboxed handlers.
    """
    query = state.get("user_query", "")
    plan = state.get("task_plan", "")
    memory = state.get("memory_context", "")
    fast = _fast_path_enabled()

    try:
        from mase_tools.mcp.tools import TOOL_REGISTRY  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {
            "action_results": "",
            "messages": [{"role": "system", "content": f"MCP 不可用: {exc!r}"}],
            "error_log": [f"action_mcp_import_failed: {exc!r}"],
        }

    if fast:
        # Cheap deterministic shortcut for benchmarks: only fire on obvious
        # "current time" intents; everything else is a no-op.
        if any(kw in query for kw in ("时间", "几点", "current time")):
            res = TOOL_REGISTRY["get_current_time"]()
            results = f"\n[MCP] get_current_time -> {res}"
            return {
                "action_results": results,
                "messages": [{"role": "system", "content": f"工具执行完毕: {results}"}],
            }
        return {
            "action_results": "",
            "messages": [{"role": "system", "content": "fast-path: 跳过 MCP"}],
        }

    schemas = _build_mcp_tool_schemas()
    system_prompt = (
        "你是 MASE 的 Action 节点。你可以调用以下 MCP 工具。"
        "若问题需要当前时间、读取本地文件或列目录，请调用对应工具；"
        "否则不要调用任何工具，直接简短回应 '无需外部工具'。"
    )
    messages = [
        {
            "role": "user",
            "content": (
                f"用户问题: {query}\n\n计划:\n{plan}\n\n已检索记忆:\n{memory}"
            ),
        }
    ]

    error: str | None = None
    results_text = ""
    try:
        response = _get_model_interface().chat(
            "executor",
            messages=messages,
            tools=schemas,
            override_system_prompt=system_prompt,
        )["message"]
    except Exception as exc:  # noqa: BLE001
        error = f"action_llm_failed: {exc!r}"
        response = {}

    tool_calls = response.get("tool_calls") if isinstance(response, dict) else None
    if tool_calls:
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            handler = TOOL_REGISTRY.get(name) if name else None
            if handler is None:
                results_text += f"\n[MCP:error] unknown tool {name!r}"
                continue
            try:
                res = handler(**args) if args else handler()
                results_text += f"\n[MCP] {name}({args}) -> {res}"
            except TypeError as exc:
                results_text += f"\n[MCP:error] bad args for {name}: {exc}"
            except Exception as exc:  # noqa: BLE001
                results_text += f"\n[MCP:error] {name} raised: {exc!r}"

    update: dict[str, Any] = {
        "action_results": results_text,
        "messages": [
            {
                "role": "system",
                "content": f"工具执行完毕: {results_text}" if results_text else "无外部动作执行。",
            }
        ],
    }
    if error:
        update["error_log"] = [error]
    return update

def executor_node(state: AgentState):
    """Executor Agent Node - 回答问题"""
    query = state.get("user_query", "")
    decision = state.get("router_decision")
    memory = state.get("memory_context", "")
    actions = state.get("action_results", "")
    
    full_context = memory
    if actions:
        full_context += f"\n【外部工具结果】\n{actions}"
    
    # 深度重构后：连接 executor
    if decision == "search_memory" or actions:
        answer = _ensure_executor().execute(query=query, memory_context=full_context)
    else:
        answer = _ensure_executor().execute(query=query, memory_context="无相关记忆。")
        
    return {"executor_result": answer, "messages": [{"role": "assistant", "content": answer}]}

def route_after_router(state: AgentState) -> str:
    if state.get("router_decision") == "search_memory":
        return "notetaker"
    return "executor"

workflow = StateGraph(AgentState)
workflow.add_node("router", router_node)
workflow.add_node("notetaker", notetaker_node)
workflow.add_node("planner", planner_node)
workflow.add_node("action", action_node)
workflow.add_node("executor", executor_node)

workflow.set_entry_point("router")
workflow.add_conditional_edges("router", route_after_router, {"notetaker": "notetaker", "executor": "action"})
workflow.add_edge("notetaker", "planner")
workflow.add_edge("planner", "action")
workflow.add_edge("action", "executor")
workflow.add_edge("executor", END)

mase_app = workflow.compile()

if __name__ == "__main__":
    print("--- 启动现代版 MASE LangGraph 引擎 (基于 SQLite) ---")
    initial_state = {
        "user_query": "我之前提到的项目代号是什么？现在几点了？",
        "messages": [{"role": "user", "content": "我之前提到的项目代号是什么？现在几点了？"}],
        "router_decision": "",
        "memory_context": "",
        "task_plan": "",
        "action_results": "",
        "executor_result": "",
        "error_log": []
    }
    
    for event in mase_app.stream(initial_state):
        for k, v in event.items():
            print(f"[{k} 节点执行完毕]")
            if "executor_result" in v:
                print(f"最终输出: {v['executor_result']}")
