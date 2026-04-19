# 生态卡位文案（中文版）

目标很明确：让 MASE 看起来不是“一个有意思的 benchmark 项目”，而是“一个正在形成中的基础设施层”。

## 1. 总定位

推荐主表述：

> MASE 正在演化成一个白盒 AI memory substrate：它提供可检查的存储、可审计的检索，以及建立在开源模型之上的可组合执行链路。

短句版本：

> 不只是 benchmark system，而是 memory layer。

## 2. MCP 方向定位

### 为什么 MCP 对 MASE 很关键

MCP 是目前把 MASE 从“仓库里的系统”变成“可被已有客户端调用的外部记忆脑”最自然的一步。

### 推荐一句话

> MASE + MCP = 把本地、可检查、可审计的记忆能力，变成任何 MCP 客户端都能调用的工具。

### README 可用片段

```md
## 为什么 MCP 是 P0 级优先项

MASE 不应该被困在自己的 demo 入口里。只要通过 MCP 暴露出去，Claude Desktop、Cursor 以及其他支持 MCP 的客户端，就可以把 MASE 当作外部记忆层来使用。

而 MASE 最有价值的地方，正是它的记忆同时具备：

- 本地可运行
- 结果可检查
- 链路可审计
- 可跨会话、跨工具复用
```

### 建议 issue 标题

1. **Ship MCP server for MASE memory operations**
2. **Expose search / write / trace inspection through MCP**
3. **Design MCP tools for memory lookup, fact-sheet inspection, and run traces**

### 可对外发布的版本

> 当 MASE 支持 MCP，它就不再只是一个 repo，而会变成客户端可调用的白盒记忆层。

## 3. OpenAI-compatible API 方向定位

### 为什么它重要

最快的扩散路径，不是让每个前端都单独适配 MASE，而是让现有前端把它当作标准 chat backend。

### 推荐一句话

> 一旦 MASE 暴露 `/v1/chat/completions`，它就会从“有意思的记忆实验”变成“可直接接入的 memory backend”。

### README 可用片段

```md
## 为什么 OpenAI-compatible API 很重要

如果 MASE 提供兼容 OpenAI 的 `/v1/chat/completions` 接口，那么现有 chat UI 和 agent framework 基本不需要额外定制，就能直接接入。

这意味着 MASE 可以进入：

- LobeChat
- Open WebUI
- AnythingLLM
- 各种内部定制工具

这不是为了“API 模仿”。这本质上是在买分发。
```

### 建议 issue 标题

1. **Expose MASE through `/v1/chat/completions`**
2. **Add OpenAI-compatible chat layer for routing + memory + execution**
3. **Support drop-in chat clients via OpenAI-compatible API**

### 可对外发布的版本

> MASE 可以在保持白盒记忆内核的同时，对外表现成标准 chat backend。

## 4. “为什么它是基础设施”段落

博客或 README 后续可以直接用这段：

> Benchmark 赢得的是注意力，基础设施赢得的是留存。一旦 MASE 能被 MCP 客户端和 OpenAI-compatible 前端调用，它就不再只是一个展示白盒记忆思想的 demo，而会开始变成开发者日常工具链里可复用的 memory layer。

## 5. 关键词建议

建议稳定使用这些标签：

- `white-box memory`
- `local AI memory`
- `auditable retrieval`
- `MCP`
- `OpenAI-compatible`
- `small-model orchestration`
- `JSON memory`
- `inspectable AI systems`

