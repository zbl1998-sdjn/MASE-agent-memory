"""
MCP Server: 把 MASE 当作 Claude Desktop / Cursor / 任何 MCP 客户端的记忆层.

启动:
    python -m integrations.mcp_server.server
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError("需要安装 MCP SDK: pip install mcp") from e

from mase import MemoryService, get_notetaker, mase_ask  # noqa: E402

mcp = FastMCP("mase-memory")
_notetaker = get_notetaker()
_memory_service = MemoryService()


def _scope_filters(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, str]:
    scope: dict[str, str] = {}
    if tenant_id:
        scope["tenant_id"] = tenant_id
    if workspace_id:
        scope["workspace_id"] = workspace_id
    if visibility:
        scope["visibility"] = visibility
    return scope


@mcp.tool()
def mase_remember(
    text: str,
    thread_id: str = "mcp::default",
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> str:
    """把任意文本写入 MASE 长期记忆 (SQLite + FTS5).

    Args:
        text: 要记住的内容
        thread_id: 会话标识, 默认 'mcp::default'
    """
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    _memory_service.remember_event(thread_id, "user", text, scope_filters=scope)
    return f"✅ remembered ({len(text)} chars) under thread '{thread_id}'"


@mcp.tool()
def mase_recall(
    query: str,
    top_k: int = 5,
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> list[dict]:
    """从 MASE 长期记忆按关键词 BM25 召回.

    Args:
        query: 查询语句
        top_k: 返回条数, 默认 5
    """
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    results = _memory_service.search_memory(
        query.split(),
        full_query=query,
        limit=top_k,
        include_history=True,
        scope_filters=scope,
    )
    return [
        {
            "content": r.get("content", ""),
            "thread": r.get("thread_id", ""),
            "source": r.get("_source", "memory_log"),
            "source_log_id": r.get("source_log_id"),
            "source_content": r.get("source_content", ""),
            "freshness": r.get("freshness"),
            "reason": r.get("retrieval_reason"),
            "tenant_id": r.get("tenant_id", ""),
            "workspace_id": r.get("workspace_id", ""),
            "visibility": r.get("visibility", ""),
        }
        for r in results
    ]


@mcp.tool()
def mase_recall_current_state(
    query: str,
    top_k: int = 5,
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> list[dict]:
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    results = _memory_service.recall_current_state(query.split(), limit=top_k, scope_filters=scope)
    return [
        {
            "content": r.get("content", ""),
            "category": r.get("category", ""),
            "key": r.get("entity_key", ""),
            "value": r.get("entity_value", ""),
            "freshness": r.get("freshness"),
            "history_depth": r.get("history_depth"),
            "tenant_id": r.get("tenant_id", ""),
            "workspace_id": r.get("workspace_id", ""),
            "visibility": r.get("visibility", ""),
        }
        for r in results
    ]


@mcp.tool()
def mase_recall_timeline(
    thread_id: str = "",
    limit: int = 20,
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> list[dict]:
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    rows = _memory_service.recall_timeline(thread_id=thread_id or None, limit=limit, scope_filters=scope)
    return [
        {
            "thread_id": r.get("thread_id", ""),
            "role": r.get("role", ""),
            "content": r.get("content", ""),
            "timestamp": r.get("event_timestamp") or r.get("timestamp") or r.get("created_at"),
            "tenant_id": r.get("tenant_id", ""),
            "workspace_id": r.get("workspace_id", ""),
            "visibility": r.get("visibility", ""),
        }
        for r in rows
    ]


@mcp.tool()
def mase_explain_answer(
    query: str,
    top_k: int = 5,
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> dict:
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    return _memory_service.explain_memory_answer(query, limit=top_k, scope_filters=scope)


@mcp.tool()
def mase_ask_tool(question: str) -> str:
    """走 MASE 完整 pipeline (路由→记忆→规划→执行) 直接回答.

    Args:
        question: 用户问题
    """
    return mase_ask(question)


@mcp.tool()
def mase_list_threads(tenant_id: str = "", workspace_id: str = "", visibility: str = "") -> list[str]:
    """列出所有 thread (会话) 标识."""
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    rows = _memory_service.recall_timeline(limit=10000, scope_filters=scope)
    return sorted({r.get("thread_id", "") for r in rows if r.get("thread_id")})


if __name__ == "__main__":
    mcp.run()
