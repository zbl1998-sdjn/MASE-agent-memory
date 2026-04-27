"""
MASE → LangChain `BaseChatMemory` adapter.

一行替换 LangChain 默认 memory:

    from integrations.langchain.mase_memory import MASEMemory
    memory = MASEMemory()
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from langchain.memory.chat_memory import BaseChatMemory  # type: ignore
    from langchain_core.messages import AIMessage, HumanMessage  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "需要安装 LangChain: pip install langchain langchain-core"
    ) from e

from mase import get_notetaker, mase_ask  # noqa: E402


class MASEMemory(BaseChatMemory):
    """LangChain BaseChatMemory backed by MASE (SQLite + FTS5).

    - 写入: 每轮 user/assistant 自动写入 SQLite (持久化, 跨进程, 跨 session)
    - 读取: 按当前 input 走 BM25 召回相关历史, 返回为 messages
    """

    memory_key: str = "history"
    return_messages: bool = True
    notetaker: Any = None
    top_k: int = 8
    thread_id: str = "langchain::default"

    def __init__(self, **kwargs: Any) -> None:
        injected_notetaker = kwargs.pop("notetaker", None)
        super().__init__(**kwargs)
        object.__setattr__(self, "notetaker", get_notetaker(injected_notetaker))

    @property
    def memory_variables(self) -> list[str]:
        return [self.memory_key]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = str(inputs.get("input") or inputs.get("question") or "").strip()
        if not query:
            return {self.memory_key: [] if self.return_messages else ""}
        results = self.notetaker.search(
            keywords=query.split(),
            full_query=query,
            limit=self.top_k,
        )
        if self.return_messages:
            messages: list[Any] = []
            for r in results:
                content = r.get("content", "")
                if "User:" in content:
                    messages.append(HumanMessage(content=content))
                else:
                    messages.append(AIMessage(content=content))
            return {self.memory_key: messages}
        text = "\n".join(r.get("content", "") for r in results)
        return {self.memory_key: text}

    def save_context(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> None:
        user = str(inputs.get("input") or inputs.get("question") or "").strip()
        assistant = str(
            outputs.get("response") or outputs.get("output") or ""
        ).strip()
        if not user and not assistant:
            return
        self.notetaker.write(
            user_query=user,
            assistant_response=assistant,
            summary=user[:120],
            thread_id=self.thread_id,
        )

    def clear(self) -> None:
        # 故意 no-op: MASE 是持久化白盒, 用 mase_cli.py 物理删除
        pass


def mase_ask_chain(question: str) -> str:
    """便捷函数: 直接用 MASE 完整 pipeline 回答, 不走 LangChain LLM."""
    return mase_ask(question)
