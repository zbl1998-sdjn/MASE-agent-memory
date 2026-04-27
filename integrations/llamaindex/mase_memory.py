"""
MASE → LlamaIndex BaseMemory adapter.

LlamaIndex 0.10+ 的 memory 接口比 LangChain 简单, 只要实现 get/put.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from llama_index.core.llms import ChatMessage, MessageRole  # type: ignore
    from llama_index.core.memory.types import BaseMemory  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "需要安装 LlamaIndex: pip install llama-index-core"
    ) from e

from mase import get_notetaker  # noqa: E402


class MASELlamaMemory(BaseMemory):
    """LlamaIndex BaseMemory backed by MASE."""

    notetaker: Any = None
    top_k: int = 8
    thread_id: str = "llamaindex::default"

    @classmethod
    def class_name(cls) -> str:
        return "MASELlamaMemory"

    def __init__(self, **kwargs: Any) -> None:
        injected_notetaker = kwargs.pop("notetaker", None)
        super().__init__(**kwargs)
        object.__setattr__(self, "notetaker", get_notetaker(injected_notetaker))

    def get(self, input: str | None = None, **kwargs: Any) -> list[ChatMessage]:
        query = (input or "").strip()
        if not query:
            return []
        results = self.notetaker.search(
            keywords=query.split(),
            full_query=query,
            limit=self.top_k,
        )
        msgs: list[ChatMessage] = []
        for r in results:
            msgs.append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=r.get("content", ""),
                )
            )
        return msgs

    def get_all(self) -> list[ChatMessage]:
        rows = self.notetaker.fetch_all_chronological(limit=200)
        return [
            ChatMessage(role=MessageRole.ASSISTANT, content=r.get("content", ""))
            for r in rows
        ]

    def put(self, message: ChatMessage) -> None:
        if message.role == MessageRole.USER:
            self.notetaker.write(
                user_query=str(message.content or ""),
                assistant_response="",
                summary=str(message.content or "")[:120],
                thread_id=self.thread_id,
            )
        else:
            self.notetaker.write(
                user_query="",
                assistant_response=str(message.content or ""),
                summary=str(message.content or "")[:120],
                thread_id=self.thread_id,
            )

    def set(self, messages: list[ChatMessage]) -> None:
        for m in messages:
            self.put(m)

    def reset(self) -> None:
        # MASE 是持久化白盒, reset 是 no-op. 用 mase_cli 物理删除.
        pass
