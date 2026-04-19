from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class AgentMessage:
    kind: str
    source: str
    target: str
    payload: dict[str, Any]
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
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
    return AgentMessage(
        kind=kind,
        source=source,
        target=target,
        payload=payload,
        thread_id=thread_id,
        metadata=metadata or {},
    )
