"""
OpenAI-compatible Chat Completions API wrapping MASE.

启动:
    python -m integrations.openai_compat.server
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    import uvicorn  # type: ignore
    from fastapi import FastAPI  # type: ignore
    from fastapi.responses import StreamingResponse  # type: ignore
    from pydantic import BaseModel  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "需要安装: pip install fastapi uvicorn"
    ) from e

from mase import MemoryService, mase_ask  # noqa: E402

app = FastAPI(title="MASE OpenAI-Compatible API")
memory_service = MemoryService()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "mase"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class MemoryRecallRequest(BaseModel):
    query: str
    top_k: int = 5
    include_history: bool = False
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MemoryTimelineRequest(BaseModel):
    thread_id: str | None = None
    limit: int = 20
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


def _last_user(msgs: list[ChatMessage]) -> str:
    for m in reversed(msgs):
        if m.role == "user":
            return m.content
    return ""


def _scope_from_request(req: Any) -> dict[str, Any]:
    return {
        key: value
        for key in ("tenant_id", "workspace_id", "visibility")
        if (value := getattr(req, key, None)) not in (None, "")
    }


def _source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("_source") or row.get("source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": "mase",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mase",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest) -> Any:
    question = _last_user(req.messages)
    answer = mase_ask(question) if question else ""
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if not req.stream:
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(question),
                "completion_tokens": len(answer),
                "total_tokens": len(question) + len(answer),
            },
        }

    def _stream() -> Any:
        chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": req.model,
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": answer},
                 "finish_reason": None}
            ],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        end = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": req.model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(end, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/v1/memory/recall")
def memory_recall(req: MemoryRecallRequest) -> dict[str, Any]:
    scope = _scope_from_request(req)
    hits = memory_service.search_memory(
        req.query.split(),
        full_query=req.query,
        limit=req.top_k,
        include_history=req.include_history,
        scope_filters=scope,
    )
    return {
        "object": "mase.memory.recall",
        "data": hits,
        "metadata": {"scope": scope, "result_count": len(hits), "source_counts": _source_counts(hits)},
    }


@app.post("/v1/memory/current-state")
def memory_current_state(req: MemoryRecallRequest) -> dict[str, Any]:
    scope = _scope_from_request(req)
    hits = memory_service.recall_current_state(req.query.split(), limit=req.top_k, scope_filters=scope)
    return {
        "object": "mase.memory.current_state",
        "data": hits,
        "metadata": {"scope": scope, "result_count": len(hits), "source_counts": _source_counts(hits)},
    }


@app.post("/v1/memory/timeline")
def memory_timeline(req: MemoryTimelineRequest) -> dict[str, Any]:
    scope = _scope_from_request(req)
    rows = memory_service.recall_timeline(thread_id=req.thread_id, limit=req.limit, scope_filters=scope)
    return {
        "object": "mase.memory.timeline",
        "data": rows,
        "metadata": {"scope": scope, "result_count": len(rows)},
    }


@app.post("/v1/memory/explain")
def memory_explain(req: MemoryRecallRequest) -> dict[str, Any]:
    scope = _scope_from_request(req)
    payload = memory_service.explain_memory_answer(req.query, limit=req.top_k, scope_filters=scope)
    return {"object": "mase.memory.explain", "data": payload, "metadata": payload.get("metadata", {})}


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
