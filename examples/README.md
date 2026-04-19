# MASE — Examples

每个示例独立可跑, 无相互依赖. 默认走本地 Ollama, 需要云端模型的会在文件头注明.

| # | 文件 | 演示能力 | 状态 |
|---|------|---------|------|
| 01 | `01_quickstart_chatbot.py` | 30 行接管 ChatGPT-style 多轮对话 | ✅ stub |
| 02 | `02_personal_assistant.py` | 跨轮记住用户偏好 (今天爱吃辣 → 明天问"我爱吃啥") | ✅ stub |
| 03 | `03_research_agent.py` | 喂 50 篇 PDF, 跨文档问答 | 📝 TODO |
| 04 | `04_long_doc_qa_256k.py` | 复现 LV-Eval 256k 88.71% | ✅ stub |
| 05 | `05_multi_session_memory.py` | 复现 LongMemEval 跨 session 推理 | 📝 TODO |
| 06 | `06_correct_my_memory.py` | "我说错了, 我其实是 28 岁" — UPDATE 能力 (向量库做不到) | ✅ stub |
| 07 | `07_anti_adversarial.py` | 上下文塞误导信息, MASE 仍答对 | 📝 TODO |
| 08 | `08_hot_swap_models.py` | 一行 env 从本地 7B 切到 GLM-5 | ✅ stub |
| 09 | `09_resume_after_crash.py` | kill -9 后下一句对话延续记忆 | ✅ stub |
| 10 | `10_persistent_chat_cli.py` | **30 秒上手**: 持久长记忆 + 零幻觉 iron-rule, `Ctrl-C` 重启后 "Welcome back" — [README_10.md](README_10.md) | ✅ 可跑 |
| 11 | `11_mcp_claude_desktop/` | 配 Claude Desktop 用 MASE 当记忆 | 📝 TODO |

## 跑法

```bash
# 任意一个示例
python examples/01_quickstart_chatbot.py
```

若需要云端模型, 在 `.env` 配 `ZHIPU_API_KEY` / `MOONSHOT_API_KEY` / `DEEPSEEK_API_KEY`.
