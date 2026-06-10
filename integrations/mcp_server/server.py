"""
MCP Server: 把 MASE 当作 Claude Desktop / Cursor / 任何 MCP 客户端的记忆层.

启动:
    python -m integrations.mcp_server.server

这个入口比 HTTP API 更薄：只暴露记忆读写和完整 ask 工具，
鉴权/隔离主要通过调用方传入的 tenant/workspace/visibility scope 完成。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
# 支持源码树直接运行 MCP server，避免面试演示前必须先安装 wheel。
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
    """统一构造 scope 过滤器；空字符串不会进入查询条件。"""
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
    text: str | int | float,
    thread_id: str = "mcp::default",
    role: str = "user",
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> str:
    """把一条对话事件写入 MASE 长期记忆 (SQLite + FTS5),返回里带 log_id 便于溯源.

    Args:
        text: 要记住的内容(纯数字内容也兼容,统一 str() 归一)
        thread_id: 会话标识, 默认 'mcp::default'
        role: 说话角色 'user' / 'assistant'(细分时间线), 默认 'user'
    """
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    # 容错:有些 MCP 客户端会把纯数字串转成 int/float,统一 str() 归一,避免如 "5050" 这种纯数字消息丢失。
    content = str(text)
    result = _memory_service.remember_event(thread_id, role, content, scope_filters=scope)
    return f"✅ remembered role={role} ({len(content)} chars); {result.get('result', '')}"


@mcp.tool()
def mase_upsert_fact(
    category: str | int | float,
    key: str | int | float,
    value: str | int | float,
    reason: str = "",
    source_log_id: int = 0,
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> str:
    """把一条结构化事实写入 MASE 当前事实表 (entity_state).

    同一个 (category, key) 再次写入不同 value 会触发 supersede:旧值被盖章进
    entity_state_history, facts-first 召回只返回最新值. 适合"用户陈述的当前事实".

    Args:
        category: 事实分类, 如 'conversation_facts'
        key: 事实键, 如 '项目代号'
        value: 事实值, 如 'ORION-7'
        reason: 写入原因(如 'user_correction'),用于审计
        source_log_id: 触发本次事实变化的对话 log_id,做"事实 ⇄ 对话"双向溯源(0=不关联)
    """
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    # 容错:有些 MCP 客户端会把纯数字串转成 int/float,这里统一 str() 归一,避免端口/房间号等数字 key/value 丢失。
    result = _memory_service.upsert_fact(
        str(category),
        str(key),
        str(value),
        reason=reason or None,
        source_log_id=source_log_id or None,
        scope_filters=scope,
    )
    return f"✅ fact upserted: {result.get('category')}.{result.get('key')} = {result.get('value')}"


@mcp.tool()
def mase_get_facts(
    category: str = "",
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> str:
    """读取 MASE 当前事实表 (entity_state) 的全部(或某分类)结构化事实.

    每条含 category / entity_key / entity_value, 适合作为"当前状态"高优先级、
    不依赖关键词召回地注入上下文,保证当前事实始终在场.
    """
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    facts = _memory_service.list_facts(category or None, scope_filters=scope)
    # 返回 JSON 字符串(而非 list[dict]):序列化进 content[].text 更稳,桥接侧解析确定。
    return json.dumps(facts, ensure_ascii=False, default=str)


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
    """只召回当前事实表，适合 MCP 客户端询问“当前状态”。"""
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
    """读取事件时间线，帮助客户端解释某条记忆来自哪段历史。"""
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
def mase_recall_thread_tail(
    thread_id: str,
    limit: int = 24,
    tenant_id: str = "",
    workspace_id: str = "",
    visibility: str = "",
) -> list[dict]:
    """取某会话线程最近 limit 条事件, 按时序升序返回(最早在前).

    适合"对话连续性"注入: 把最近几轮原样喂回模型, 回答"我第一句说了啥 /
    刚才聊了啥 / 接着上文"这类按时间顺序的问题. thread 过滤在 SQL 内先于 LIMIT,
    取的是该线程最近 N 条, 而非全局最早 N 条里恰属于该线程的.
    """
    scope = _scope_filters(tenant_id or None, workspace_id or None, visibility or None)
    rows = _memory_service.recall_thread_tail(thread_id=thread_id, limit=limit, scope_filters=scope)
    return [
        {
            "role": r.get("role", ""),
            "content": r.get("content", ""),
            "timestamp": r.get("event_timestamp") or r.get("timestamp") or r.get("created_at"),
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
    """返回回答所依赖的证据链，而不是只给最终答案。"""
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
