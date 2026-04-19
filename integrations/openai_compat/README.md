# OpenAI-Compatible API for MASE

把 MASE 包装成 OpenAI Chat Completions API (`/v1/chat/completions`),
任何 OpenAI 客户端 (官方 SDK, Cherry Studio, OpenWebUI, NextChat, ...)
**零改造**接入.

## 安装

```bash
pip install fastapi uvicorn
```

## 启动

```bash
python -m integrations.openai_compat.server
# 默认 http://127.0.0.1:8765
```

## 客户端用法

```python
from openai import OpenAI
client = OpenAI(api_key="not-needed", base_url="http://127.0.0.1:8765/v1")
resp = client.chat.completions.create(
    model="mase",
    messages=[{"role": "user", "content": "我多大?"}],
)
print(resp.choices[0].message.content)
```

## Cherry Studio / OpenWebUI 配置

把 base URL 设成 `http://127.0.0.1:8765/v1`, 模型名填 `mase`. 完事.

## 已实现的端点

| 端点 | 状态 |
|------|------|
| `POST /v1/chat/completions` (non-stream) | ✅ |
| `POST /v1/chat/completions` (stream) | ✅ (伪流式: 一次性吐) |
| `GET /v1/models` | ✅ |

## 已知限制

- 暂不支持 function calling / tools (MASE 内部已经有 router/planner, 外部 tools 后续接入 MCP 层)
- 暂不支持 vision/audio
