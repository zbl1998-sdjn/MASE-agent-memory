# Example 10 — MCP: 把 MASE 挂给 Claude Desktop / Cursor

通过 MCP (Model Context Protocol) 把 MASE 暴露成一个标准 MCP server,
然后让 Claude Desktop / Cursor / 任何 MCP 客户端把 MASE 当作记忆层使用.

完整代码与配置示例见 [`integrations/mcp_server/`](../../integrations/mcp_server/).

## Claude Desktop 一键配置

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

重启 Claude Desktop. 工具列表会出现:
- `mase_remember(text)` — 写入长期记忆
- `mase_recall(query)` — BM25 召回历史
- `mase_ask(question)` — 走完整 MASE pipeline 回答
- `mase_list_threads()` — 列出所有会话
