from __future__ import annotations

import json
import os
import time
from typing import Any

from mase_tools.memory import tri_vault
from mase_tools.memory.api import (
    mase2_correct_and_log,
    mase2_get_fact_history,
    mase2_get_facts,
    mase2_search_memory,
    mase2_supersede_facts,
    mase2_upsert_fact,
    mase2_write_interaction,
)
from .model_interface import ModelInterface

# Maps notetaker tool names to the tri-vault bucket they should mirror into.
# Read-only tools (search/get_*) are intentionally absent — they don't mutate
# memory and so produce no on-disk artifact. Default-bucket fallback in
# ``_mirror_tool_write`` is "sessions" per the wire-up spec.
_TRI_VAULT_BUCKET_BY_TOOL = {
    "mase2_write_interaction": "sessions",
    "mase2_upsert_fact": "context",
    "mase2_correct_and_log": "state",
    "mase2_supersede_facts": "state",
}

NOTETAKER_SYSTEM = """
你是记事智能体，负责管理外部记忆。
- 每次对话结束时，你需要保存原始对话记录，调用 mase2_write_interaction 记录用户的查询和助手的回答。
- 当识别到新的事实（如用户偏好、财务预算、时间安排等），你应该调用 mase2_upsert_fact 来更新或插入该事实。
- 需要查找历史对话记录时，调用 mase2_search_memory。
- 需要了解用户的核心状态或当前偏好时，调用 mase2_get_facts。
- 你只负责结构化记忆操作，不负责面向用户的最终回答。
"""

NOTETAKER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "mase2_write_interaction",
            "description": "记录当前的对话流水账。",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_id": {"type": "string", "description": "当前对话的线程ID"},
                    "role": {"type": "string", "description": "发言角色 (如 'user' 或 'assistant')"},
                    "content": {"type": "string", "description": "对话内容"},
                },
                "required": ["thread_id", "role", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mase2_upsert_fact",
            "description": "提取并更新实体状态（Entity Fact），以覆盖旧记忆。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "实体的类别，如 'finance_budget', 'user_preferences', 'project_status'"},
                    "key": {"type": "string", "description": "实体的唯一标识键，如 'monthly_food_budget'"},
                    "value": {"type": "string", "description": "实体的当前值"},
                },
                "required": ["category", "key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mase2_search_memory",
            "description": "使用 BM25 全文检索搜索历史对话记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "搜索关键词列表",
                    },
                    "limit": {"type": "integer", "description": "返回结果的数量上限", "default": 5},
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mase2_get_facts",
            "description": "获取指定的实体状态列表，了解核心事实或上下文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "要查询的类别（可选），如果不提供则返回所有事实"},
                },
            },
        },
    },
]

class NotetakerAgent:
    def __init__(self, model_interface: ModelInterface | None = None) -> None:
        self.model_interface = model_interface
        self._tool_handlers: dict[str, Any] = {
            "mase2_write_interaction": mase2_write_interaction,
            "mase2_upsert_fact": mase2_upsert_fact,
            "mase2_search_memory": mase2_search_memory,
            "mase2_get_facts": mase2_get_facts,
            "mase2_correct_and_log": mase2_correct_and_log,
            "mase2_supersede_facts": mase2_supersede_facts,
            "mase2_get_fact_history": mase2_get_fact_history,
        }

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return NOTETAKER_TOOLS

    def select_operation_mode(self, user_message: str, context: str = "") -> str:
        # 默认模式
        return "default"

    def parse_tool_arguments(self, raw_arguments: Any) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if isinstance(raw_arguments, str):
            stripped = raw_arguments.strip()
            try:
                return json.loads(stripped) if stripped else {}
            except json.JSONDecodeError as exc:
                raise ValueError(f"无法解析工具参数 JSON: {stripped!r}") from exc
        raise TypeError(f"无法解析工具参数: {raw_arguments!r}")

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._tool_handlers:
            raise ValueError(f"未知工具: {name}")
        result = self._tool_handlers[name](**arguments)
        if name == "mase2_search_memory" and os.environ.get("MASE_HYBRID_RECALL", "0") == "1":
            try:
                from .hybrid_recall import HybridReranker
                if isinstance(result, list) and result and isinstance(result[0], dict):
                    query = " ".join(arguments.get("keywords") or []) if isinstance(arguments, dict) else ""
                    result = HybridReranker().rerank(query, result)
            except Exception:
                pass
        return result

    def execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call["function"]
        name = function["name"]
        arguments = self.parse_tool_arguments(function.get("arguments", {}))
        result = self.execute_tool(name, arguments)
        # Tri-vault mirror: SQLite write has succeeded above (api.* commits
        # before returning), so it's safe to mirror to the on-disk vault now.
        # No-op when MASE_MEMORY_LAYOUT != "tri".
        self._mirror_tool_write(name, arguments, result)
        return {
            "name": name,
            "arguments": arguments,
            "result": result,
        }

    @staticmethod
    def _mirror_tool_write(name: str, arguments: dict[str, Any], result: Any) -> None:
        if not tri_vault.is_enabled():
            return
        if name not in _TRI_VAULT_BUCKET_BY_TOOL:
            return
        bucket = _TRI_VAULT_BUCKET_BY_TOOL.get(name, "sessions")
        # Build a stable, human-grep-friendly key per tool.
        if name == "mase2_write_interaction":
            thread_id = str(arguments.get("thread_id", "unknown"))
            role = str(arguments.get("role", "unknown"))
            key = f"{thread_id}__{int(time.time() * 1000)}__{role}"
        elif name == "mase2_upsert_fact":
            key = f"{arguments.get('category', 'misc')}__{arguments.get('key', 'unknown')}"
        elif name == "mase2_correct_and_log":
            key = f"correction__{arguments.get('thread_id', 'unknown')}__{int(time.time() * 1000)}"
        elif name == "mase2_supersede_facts":
            key = f"supersede__{int(time.time() * 1000)}"
        else:
            key = f"{name}__{int(time.time() * 1000)}"
        try:
            tri_vault.mirror_write(
                bucket,
                key,
                {"tool": name, "arguments": arguments, "result": result},
            )
        except Exception:
            # Mirror is best-effort; a vault write failure must never break the
            # primary SQLite-backed memory path.
            pass

    def chat_with_tools(self, user_message: str, context: str = "", mode: str | None = None) -> dict[str, Any]:
        if self.model_interface is None:
            raise RuntimeError("NotetakerAgent 缺少 ModelInterface，无法进行模型工具调用。")

        user_content = f"{context}\n用户指令：{user_message}".strip()
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        effective_mode = mode or self.select_operation_mode(user_message, context)

        first_response = self.model_interface.chat(
            "notetaker",
            messages=messages,
            mode=effective_mode,
            tools=self.get_tool_schemas(),
            override_system_prompt=NOTETAKER_SYSTEM
        )["message"]

        final_response = first_response.get("content", "").strip()
        executed_tools: list[dict[str, Any]] = []

        if first_response.get("tool_calls"):
            messages = messages + [first_response]
            for tool_call in first_response["tool_calls"]:
                executed = self.execute_tool_call(tool_call)
                executed_tools.append(executed)
                messages.append(
                    {
                        "role": "tool",
                        "name": executed["name"],
                        "content": json.dumps(executed["result"], ensure_ascii=False),
                    }
                )

            follow_up = self.model_interface.chat(
                "notetaker", 
                messages=messages, 
                mode=effective_mode, 
                override_system_prompt=NOTETAKER_SYSTEM
            )["message"]
            final_response = follow_up.get("content", "").strip()

        return {
            "mode": effective_mode,
            "initial_response": first_response.get("content", "").strip(),
            "final_response": final_response,
            "tool_results": executed_tools,
        }

DEFAULT_NOTETAKER = NotetakerAgent()
