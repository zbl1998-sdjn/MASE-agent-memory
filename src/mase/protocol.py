"""agent 间传递消息的轻量协议对象。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    """统一消息时间戳格式，避免调用方各自格式化。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class AgentMessage:
    """不可变消息信封；payload 承载具体业务内容。"""

    kind: str
    source: str
    target: str
    payload: dict[str, Any]
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "payload": self.payload,
            "thread_id": self.thread_id,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


def make_message(
    kind: str,
    source: str,
    target: str,
    payload: dict[str, Any],
    thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentMessage:
    """创建 AgentMessage，并把缺省 metadata 规整为空字典。"""
    return AgentMessage(
        kind=kind,
        source=source,
        target=target,
        payload=payload,
        thread_id=thread_id,
        metadata=metadata or {},
    )
