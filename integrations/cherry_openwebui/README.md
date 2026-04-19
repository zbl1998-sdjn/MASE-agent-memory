# Cherry Studio / OpenWebUI 接入 MASE

Cherry Studio / OpenWebUI / NextChat / ChatGPT-Next-Web 等客户端都支持
"自定义 OpenAI 兼容端点", 所以接入 MASE 不需要单独写插件 — 直接用
[`integrations/openai_compat/`](../openai_compat/) 即可.

## 步骤

1. 启动 MASE OpenAI 兼容服务

```bash
python -m integrations.openai_compat.server
# → http://127.0.0.1:8765
```

2. **Cherry Studio**: 设置 → 模型服务 → 添加自定义供应商
   - API Base URL: `http://127.0.0.1:8765/v1`
   - API Key: 任意 (例如 `not-needed`)
   - 模型: `mase`

3. **OpenWebUI**: 设置 → Connections → OpenAI API
   - API Base URL: `http://127.0.0.1:8765/v1`
   - API Key: 任意

4. **NextChat / ChatGPT-Next-Web**: 设置 → 自定义模型
   - 接口地址: `http://127.0.0.1:8765/v1`
   - 模型名: `mase`

## 验证

```bash
python mase_cli.py
```

看刚才的对话是否落入 SQLite.

## 远程访问

```bash
uvicorn integrations.openai_compat.server:app --host 0.0.0.0 --port 8765
```

> ⚠️ 公网暴露前加 API Key 认证 + 防火墙白名单.
