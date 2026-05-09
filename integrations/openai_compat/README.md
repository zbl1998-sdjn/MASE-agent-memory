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
| `GET /health` | ✅ |
| `GET /v1/ui/bootstrap` | ✅ |
| `GET /v1/ui/dashboard` | ✅ |
| `POST /v1/mase/run` | ✅ |
| `GET/POST /v1/memory/timeline` | ✅ |
| `GET/POST/DELETE /v1/memory/facts` | ✅ |
| `POST /v1/memory/events` | ✅ |
| `POST /v1/memory/corrections` | ✅ |
| `GET/POST/DELETE /v1/memory/session-state` | ✅ |
| `GET/POST /v1/memory/procedures` | ✅ |
| `GET/POST /v1/memory/snapshots` | ✅ |

## 可视化平台

仓库内置 Vite + React 可视化平台，覆盖健康检查、运营 cockpit、图表化记忆分布、聊天/Trace、召回解释、事实管理、时间线、会话状态、Procedure 与快照。

```bash
# 终端 1：启动 MASE API（开发模式）
pip install -e ".[server]"
python -m integrations.openai_compat.server

# 终端 2：启动前端
cd frontend
npm install
npm run dev
```

开发模式默认访问 `http://127.0.0.1:5173`，通过 Vite proxy 调用 `http://127.0.0.1:8765`。生产构建使用：

```bash
cd frontend
npm run build
```

构建完成后，`python -m integrations.openai_compat.server` 会在检测到 `frontend/dist/index.html` 时直接托管前端，访问 `http://127.0.0.1:8765` 即可进入平台。

Windows 一键构建并启动：

```powershell
Set-Location -LiteralPath 'E:\MASE-demo'
.\scripts\start_platform.ps1
```

## 已知限制

- 暂不支持 function calling / tools (MASE 内部已经有 router/planner, 外部 tools 后续接入 MCP 层)
- 暂不支持 vision/audio
