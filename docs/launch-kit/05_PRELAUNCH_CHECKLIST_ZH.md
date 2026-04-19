# 发射前 Checklist（中文版）

这是把 MASE 从“有意思”推进到“值得 Star、值得传播”的最短路径。

## P0：大规模分发前必须补齐

1. **补一条真正的一键体验路径**
   - 理想形态：`docker-compose up -d`
   - 次优形态：一个 bootstrap 脚本，负责拉模型、检查 Ollama、启动 demo

2. **补一个 3 分钟 proof demo**
   - 一次 memory write
   - 一次基于记忆的回答
   - 一张或一个 GIF，展示 JSON / Markdown 已真实落盘

3. **把 benchmark 证据前置**
   - 把最强的 LV-Eval 证据放到 README 上半区
   - 保持 anti-decay 这类表述的严谨边界

4. **补一张架构冲突图**
   - MASE vs vector DB / RAG

5. **把白盒证据直接亮出来**
   - `memory/`
   - `memory/logs/`
   - fact sheet 或 trace 截图

## P1：首波发射后立刻跟进

1. **Ship MCP server**
2. **Ship OpenAI-compatible `/v1/chat/completions`**
3. **做一个短视频或 GIF**
4. **补一条“你自己复现实验”的路径**
5. **补一个 “What MASE is / What MASE is not” 小节**

## 文案护栏

建议高频使用：

- “white-box”
- “inspectable”
- “auditable”
- “small-model system design”
- “plain-file memory”

尽量避免：

- “AGI memory”
- “vector DBs are dead”
- “fully deterministic answers”
- “state of the art everywhere”

## 发射顺序建议

1. 更新 README 的 hero 和 proof block
2. 发布 launch blog
3. 发 Show HN
4. 发 r/LocalLLaMA
5. 发 r/MachineLearning
6. 发带图的 X thread，重点展示 chart 和文件系统证据
7. 在首波流量到来后尽快跟进 MCP / API roadmap

