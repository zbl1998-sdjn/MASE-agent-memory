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

from mase import BenchmarkNotetaker, mase_ask  # noqa: E402


mcp = FastMCP("mase-memory")
_notetaker = BenchmarkNotetaker()


@mcp.tool()
def mase_remember(text: str, thread_id: str = "mcp::default") -> str:
    """把任意文本写入 MASE 长期记忆 (SQLite + FTS5).

    Args:
        text: 要记住的内容
        thread_id: 会话标识, 默认 'mcp::default'
    """
    _notetaker.write(
        user_query=text,
        assistant_response="",
        summary=text[:120],
        thread_id=thread_id,
    )
    return f"✅ remembered ({len(text)} chars) under thread '{thread_id}'"


@mcp.tool()
def mase_recall(query: str, top_k: int = 5) -> list[dict]:
    """从 MASE 长期记忆按关键词 BM25 召回.

    Args:
        query: 查询语句
        top_k: 返回条数, 默认 5
    """
    results = _notetaker.search(
        keywords=query.split(),
        full_query=query,
        limit=top_k,
    )
    return [
        {"content": r.get("content", ""), "thread": r.get("thread_id", "")}
        for r in results
    ]


@mcp.tool()
def mase_ask_tool(question: str) -> str:
    """走 MASE 完整 pipeline (路由→记忆→规划→执行) 直接回答.

    Args:
        question: 用户问题
    """
    return mase_ask(question)


@mcp.tool()
def mase_list_threads() -> list[str]:
    """列出所有 thread (会话) 标识."""
    rows = _notetaker.fetch_all_chronological(limit=10000)
    return sorted({r.get("thread_id", "") for r in rows if r.get("thread_id")})


if __name__ == "__main__":
    mcp.run()
