# MCP Server: MASE-as-Memory for Claude Desktop / Cursor / etc.

把 MASE 暴露成标准 MCP server, 任何 MCP 客户端 (Claude Desktop, Cursor,
Cline, Cherry Studio, ...) 都能挂上 MASE 作为长期记忆层.

## 安装

```bash
pip install mcp
```

## 启动

```bash
python -m integrations.mcp_server.server
```

## Claude Desktop 配置

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mase-memory": {
      "command": "python",
      "args": ["-m", "integrations.mcp_server.server"],
      "cwd": "E:\\MASE-demo",
      "env": {"PYTHONPATH": "E:\\MASE-demo\\src"}
    }
  }
}
```

## 暴露的工具

| 工具 | 用途 |
|------|------|
| `mase_remember(text, thread_id?)` | 写入长期记忆 |
| `mase_recall(query, top_k?)` | BM25 召回相关历史 |
| `mase_ask(question)` | 走完整 MASE pipeline 回答 |
| `mase_list_threads()` | 列出所有 thread |
