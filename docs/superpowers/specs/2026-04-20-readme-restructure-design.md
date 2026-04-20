# README 重构设计：MASE 记忆引擎优先版

## 问题定义

当前 `README.md` 已经具备很强的内容资产：双白盒定位、真实 benchmark、并发审计、生态集成、示例与文档链接都比较完整。问题不在内容弱，而在于信息层级混杂：

- 首页同时承载项目定义、宣言、benchmark、集成、配置、开发者自述，阅读压力过大
- “双白盒记忆引擎”“五节点运行时”“benchmark 工程项目”三条叙事并行，项目第一身份不够稳定
- 中英文 README 有少量口径和细节不一致
- 仍残留 `MASE-demo` clone / citation / star-history 链接，直接伤害可信度

本次改造的目标不是推倒重写，而是**围绕真实项目形态重组 README 的阅读动线**。

## 主定位

MASE 在首页的第一定位固定为：

> **双白盒 Agent 记忆引擎**

其他能力作为支撑层出现：

- benchmark：证明它值得信
- runtime / LangGraph / MCP：证明它可运行
- integrations：证明它能接入真实生态

## 目标

1. 让陌生访客在 20~30 秒内理解 MASE 的第一身份
2. 保留最强证据，但避免 benchmark 淹没项目定义
3. 统一“记忆架构”与“运行时实现”的表述边界
4. 修复 README 中所有 `MASE-demo` 残留与信任裂缝
5. 让中文 README 与英文 README 的结构、口径、关键信息对齐

## 非目标

- 不重写整个 README 的论点体系
- 不删除已有 benchmark 与审计结论
- 不把 README 改成纯营销页
- 不在这次调整中改动代码逻辑或 benchmark 数字

## 目标读者

### 第一读者

- 对 Agent memory / long-context / personal agent 感兴趣的工程师
- 讨厌黑盒向量记忆、关注可调试性的开发者

### 第二读者

- 想把 MASE 接入 LangChain / MCP / OpenAI compatible 接口的集成者
- 对 benchmark 可信度敏感的技术读者

## 信息架构

新 README 的主线固定为：

1. **MASE 是什么**
2. **为什么不做黑盒记忆**
3. **它如何工作**
4. **为什么值得信**
5. **如何上手**
6. **适用边界与路线图**

也就是：**定义先于证据，证据先于细节。**

## 推荐章节结构

```md
# MASE
一句话定义
一句 headline claim

[badges]
[1 张核心图]

## What MASE Is
## Why Not Black-Box Memory
## How MASE Works
## Evidence
## Quick Start
## Integrations
## Limitations
## Roadmap
## Contributing
```

## 内容分流策略

### 保留在主 README 的内容

- 双白盒定义（SQLite / Markdown / tri-vault / 可 `SELECT` / `UPDATE`）
- 三组最强 benchmark 结果
  - LV-Eval 256k
  - NoLiMa 32k
  - LongMemEval-S
- 并发安全结论
- 关键集成能力

### 压缩但保留的内容

- Anti-RAG Manifesto：压缩成短版判断句
- 并发 hazard 表：保留最关键几条
- examples 概览：只保留代表性入口
- env-gate：只保留最关键变量

### 下沉到其他文档的内容

- benchmark 方法学与长解释 → `BENCHMARKS.md`
- 详细决策背景 → `DECISIONS.md`
- 全量示例清单 → `examples/README.md`
- 长篇开发者自述 → README 尾部缩短或外链

## 叙事边界

README 中需要明确区分两件事：

### 1. 记忆架构（主叙事）

- Event Log
- Entity Fact Sheet
- Dual-whitebox storage
- Fact replacement over fact accumulation

### 2. 运行时执行流（实现层）

- Router
- Notetaker
- Planner
- Action
- Executor

首页主定义不能被五节点执行流抢走。执行流应该作为“MASE 如何落地实现记忆引擎”的说明，而不是项目第一身份。

## 写法原则

1. **语气硬，但不躁**
   - 保留技术立场
   - 删除会降低工程信任的情绪化措辞
2. **用工程因果解释优势**
   - 为什么事实覆盖降低冲突
   - 为什么白盒链路降低调试成本
   - 为什么 MASE 能把模型窗口和任务长度解耦
3. **承认边界**
   - 当前不把自己包装成通用语义检索终局方案
   - 主动承认语义泛化仍在推进

## 需要明确修复的问题

1. 所有 `MASE-demo` 残留链接
   - clone URL
   - `cd` 路径
   - citation URL
   - star history URL
2. 中英文 README 的结构差异和口径漂移
3. 首页信息过载
4. “四层记忆哲学 / 五节点执行流”混线

## 实施范围

本次修改至少覆盖：

- `README.md`
- `docs/README_en.md`

可能连带更新：

- 锚点引用
- 链接路径
- 轻量文案引用（若 README 下沉后需调整跳转）

## 预期结果

重构完成后，访客应能快速形成以下印象：

1. **MASE 是双白盒 Agent 记忆引擎**
2. **它的优势来自事实管理与白盒检索，而不是更大的上下文硬塞**
3. **它不是概念稿：有 benchmark、有审计、有集成、有示例**
4. **它知道自己的边界，且路线图清晰**

## 实施检查清单

- 重新组织中文 README 首页与章节顺序
- 对英文 README 做结构镜像
- 修复所有 `MASE-demo` 残留
- 压缩 manifesto / env-gate / examples / developer note
- 保留最强 benchmark 与并发审计背书
- 统一“记忆引擎优先”的主叙事
