# MASE 2.0 — Ecosystem Integrations

把 MASE 接入主流 LLM 框架 / 客户端, 让用户**零改造**接入.

| 集成 | 路径 | 工作量 | 状态 |
|------|------|--------|------|
| LangChain `BaseChatMemory` | `langchain/` | 1d | ✅ MVP |
| LlamaIndex `BaseMemory` | `llamaindex/` | 0.5d | ✅ MVP |
| MCP Server (Claude Desktop / Cursor) | `mcp_server/` | 1d | ✅ MVP |
| OpenAI Assistants API 兼容层 | `openai_compat/` | 2d | ✅ MVP (FastAPI) |
| Cherry Studio / OpenWebUI 插件 | `cherry_openwebui/` | 1d | 📝 文档 + OpenAI-兼容模式即可 |

每个目录下有自己的 `README.md` 说明用法.

## 设计原则

1. **零侵入**: 上层框架不改一行代码就能用 MASE 替换默认记忆
2. **零依赖**: 集成层只 import MASE 公共 API (`mase_ask`, `BenchmarkNotetaker`)
3. **可降级**: MASE 不可用时回退到框架默认行为, 不让用户卡死
