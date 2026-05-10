# MASE 项目面试讲稿

> 适用岗位：月之暗面 Agent Engineer / 同类 Agent 基础设施岗位
> 核心策略：讲"问题-假设-验证"，不要平铺功能列表

---

## 一、5 分钟快速版（电梯演讲）

**目标**：让面试官记住三样东西——**反共识主张**、**硬核数据**、**工程洁癖**。

### 开场（30s）：抛出问题

"行业做 Agent 记忆，默认假设是'向量数据库 + RAG'。但我发现这个假设有三个致命问题：
1. **事实会更新，向量只会堆积**——旧事实和新事实挤在一起，模型根本分不清；
2. **黑盒不可审计**——记忆出错时，你打不开向量空间，只能干瞪眼；
3. **长上下文被当成窗口竞赛**——大家拼命卷 128k、256k，但核心问题是上下文治理，不是窗口大小。"

### 假设与方案（90s）：MASE 是什么

"所以我做了 MASE，一个**双白盒 Agent 记忆引擎**。核心就一句话：

> **先治理记忆，再喂模型上下文。**

它把记忆拆成两类对象：
- **Event Log**：SQLite + FTS5，保留原始对话和检索入口；
- **Entity Fact Sheet**：结构化事实表，新事实**覆盖**旧事实，从根源上消灭冲突。

Runtime 是 5 节点编排——Router → Notetaker → Planner → Action → Executor。整个核心只有 2.72 MB，不靠大模型暴力堆参数，靠架构解决问题。"

### 验证（90s）：用数据说话

"为了验证这个假设，我跑了三个业界公认的 long-context / long-memory benchmark：

| Benchmark | 裸模型 | +MASE | 提升 |
|---|---|---|---|
| **LV-Eval 256k** | 4.84% | **88.71%** | **+84pp** |
| **NoLiMa 32k** | 1.79% | **60.71%** | **+59pp** |
| **LongMemEval-S** | 72.4% LLM-judge | **80.2%** | **+7.8pp** |

这里最重要的是 LV-Eval：一个**本地 7B 模型**，在没有吃到完整 256k 上下文的情况下，靠记忆压缩和事实提纯，跑到了 88.71%。这说明**架构本身，而不是参数量，决定了长上下文是否可用**。"

### 工程闭环（60s）：证明你是工程师不是炼丹师

"而且我建了完整的 Eval hygiene：
- 有 benchmark runner，支持 per-case memory isolation；
- 有 LLM-as-judge，但用了**保守策略**——只升级 substring-fail 到 pass，绝不降级，防止评委模型 bias；
- 有 anti-overfit policy 文档化，明确禁止 qid-based routing、cherry-picked reruns；
- 所有 public claim 都带 evidence manifest，CI 里跑 audit。

这套东西不是为了发论文，是为了让迭代**可回归、可复现、不骗人**。

最后，MASE 不是概念稿。它有 LangChain / LlamaIndex 内存适配、MCP Server、OpenAI-compatible 端点，现在就能接进现有生态。"

### 收尾（30s）：收束到岗位

"所以我做 MASE 的过程，其实就是把'Agent 内核'、'Eval Platform'、'Tools 集成'这三件事，在一个约束极严的环境里（本地 7B、透明记忆、可审计）全部跑了一遍。这正是贵司 JD 里要求的几个方向。"

---

## 二、15 分钟深挖版（分模块展开）

**前提**：面试官大概率会在 5 分钟版里某个点打断你。以下模块可以独立展开，也可以按需跳过。

---

### 模块 A：动机与反共识（3 分钟）

**讲什么**：为什么整个行业都在用向量数据库，你却要反对它？

**台词**：

"向量数据库在语义检索上确实有用，但把它作为 Agent 记忆的**默认底座**，我觉得是产品假设错误。

举个例子：用户第一周说'我喜欢川菜'，第二周说'我最近胃不好，不吃辣了'。在向量数据库里，这两条会同时存在，召回时可能都命中，模型看到'喜欢川菜'和'不吃辣'放在一起，就懵了——这不是模型笨，是**存储层没有提供事实覆盖的语义**。

MASE 的做法是：Notetaker 在写入时做实体抽取和冲突检测，把'饮食偏好'这个 slot 的旧值直接覆盖。Event Log 里保留原始对话供审计，但 Entity Fact Sheet 永远只呈现**当前有效事实集**。

这带来一个副作用：记忆变得**人机可读**。用户可以打开 Markdown 文件直接看到自己的记忆长什么样，甚至可以手动改。这是向量数据库永远做不到的体验。"

**可能追问**："那同义词怎么办？比如用户先说'预算 5000'，后来问'经费上限'？"

**预案**："这是 MASE 当前 admitted 的边界。我的 roadmap 是 write-time tags + read-time expansion，用 FTS5 做关键词扩写，必要时接一层 lightweight embedding 做 fallback。但核心原则不变：**先结构化治理，再谈语义泛化**。"

---

### 模块 B：架构设计（4 分钟）

**讲什么**：5 节点管道 + 存储分层 + 关键工程决策。

**台词**：

"Runtime 是 5 节点：

1. **Router**：决定走 memory retrieval 还是 direct answer。为了控制延迟，我做了 keyword fast-path——如果 query 里没有指代词（'上次'、'那个'），直接跳过检索。
2. **Notetaker**：唯一有写权限的节点。通过工具调用（`mase2_upsert_fact`、`mase2_write_interaction`）操作记忆，而不是让模型直接生成 SQL。
3. **Planner**：只做任务分解，不做最终回答。输出 ≤4 步的执行计划，每一步都有明确的输入输出契约。
4. **Action / Executor**： Executor 在生成最终答案前，会加载 Entity Fact Sheet 作为上下文，并套用 iron-rule safety prompt。

存储分三层：
- **L0**：运行时的 Python 对象（Pydantic v2 约束，非法状态不可表示）
- **L1**：SQLite + FTS5，负责结构化检索和事件流水
- **L2**：Markdown tri-vault（sessions / context / state），负责人类可读、可迁移、可审计

这里有一个工程决策：为什么用 SQLite 而不是 PostgreSQL？
不是因为 SQL 语法简单，而是因为 SQLite 的**单文件特性**完美匹配 Agent 记忆的'可携带'需求——一个用户的记忆就是一个 `.db` 文件，备份、迁移、审计都极其简单。这也是透明性的一部分。"

**代码展示点**（如果面试官要看）：打开 `src/mase/protocol.py` 的 `AgentMessage` dataclass——frozen、typed、带 UTC 时间戳，展示你对不可变消息和类型安全的执着。

---

### 模块 C：长上下文压缩策略（4 分钟）

**讲什么**：7B 模型怎么跑 256k？这是最能体现"知其所以然"的模块。

**台词**：

"MASE 能在 256k 场景下用 7B 模型跑出 88.71%，靠的不是模型能力，是**上下文治理策略**。

核心有四个方面：

**1. Mode Selector 自动分桶**
根据输入长度自动选择策略：16k 以下直接全量，64k 启动 fact-sheet 压缩，256k 启用 multi-pass retrieval。不是硬编码，而是按 length bucket 调 `search_limit` 和 `window_radius`。

**2. Multi-Pass Retrieval**
由一个小模型做 query rewrite，生成 2-3 个 paraphrase；同时跑 HyDE（Hypothetical Document Embedding）——让模型先草稿一个假想答案，从中提取关键词再做第二轮检索。最后用 cross-encoder（`bge-reranker-v2-m3`）做精排。

**3. Hybrid Recall**
不是纯向量，而是 `α·dense + β·BM25 + γ·temporal`。其中 temporal 是一个小规则引擎，检测'昨天'、'上周'、'上个月'这类时间词，动态提升近期事件的权重。

**4. Fact-Sheet 压缩**
最终喂给 Executor 的上下文，不是原始 256k 文本，而是经过 Notetaker 提纯后的 Entity Fact Sheet。通常只有几千 token，但覆盖了用户关心的全部实体状态。

这四个策略组合起来，模型从来没有看到过完整长文本，但它拿到的上下文是**经过治理的最小必要事实集**。"

**可能追问**："如果 retrieval 漏了关键信息怎么办？"

**预案**："这就是 adaptive verification 的作用。如果 retrieval score 低于阈值，或者候选答案 confidence 不够，系统会自动触发 verifier-depth routing——用更强的模型或更贵的检索策略做二次确认。这是一个成本-质量的 trade-off gate。"

---

### 模块 D：Eval 体系与 Anti-Overfit（4 分钟）

**讲什么**：这是 JD 里的核心要求，也是你最该炫耀的部分。

**台词**：

"我做 Eval 的哲学是：**数字会骗人，工程师的责任是让数字诚实**。

MASE 的 benchmark 体系有五个层次：

**1. Runner 层**
`benchmarks/runner.py` 支持 config profile 解析、per-case memory isolation、结果持久化。每个 case 跑完都会清掉记忆，防止 case 之间互相污染。

**2. Ablation Baseline**
所有报告都必须带 **naked baseline**——同一个模型，不加 MASE，裸跑 benchmark。这样才能证明提升来自架构，不是模型本身变强了。

**3. LLM-as-Judge 的保守策略**
评委模型（我用的是 kimi-k2.5 和 GLM-5）天然有长度偏见和格式偏见。我的做法是：
- 只升级，不降级：substring match 失败时，如果 judge 认为答案对，可以升级成 pass；但 substring 过了，judge 不能把它打回 fail。
- 解耦评分维度：内容正确性和格式遵从性分开打分。
- 位置交换：A/B test 时交换答案位置测两次，消除位置偏见。

**4. Anti-Overfit Policy**
这是文档化在 `BENCHMARK_ANTI_OVERFIT.md` 里的硬性规定：
- 禁止 qid-based routing（不能根据题目 ID 决定走哪条策略）；
- 禁止 cherry-picked reruns 作为 headline；
- post-hoc retry 只能标注为 diagnostic，不能混入 public claim。

**5. Evidence Provenance**
每个 public claim 都有 manifest，声明数据来源、样本数、SHA-256 fingerprint、anti-overfit 协议版本。CI 会跑 `scripts/audit_anti_overfit.py --strict` 拦截违规提交。

这套东西的目的不是炫技，是让团队迭代时**敢改代码、不怕回退**。"

---

## 三、面试官高频追问 & 应答预案

### Q1："如果 Kimi 要接入你的 MASE，你觉得最优先改哪一点？"

**答**："我会优先做**异步 server-grade runtime**。当前 MASE 的主路径还是 CLI/benchmark 级别的单进程，如果要承接 Kimi 的生产流量，需要：
- SQLite → PostgreSQL + 按 user_id 分片；
- 单进程 event bus → Redis Stream / Kafka；
- 加分布式 session 和无状态化。

但核心存储抽象（Event Log + Fact Sheet）不需要改，它天然适合按用户分片。"

### Q2："你的记忆覆盖策略会不会导致信息丢失？比如用户说'不吃辣'是暂时的，过两周又想吃辣了？"

**答**："好问题。当前 MASE 的覆盖是'最新有效'语义，确实会丢失历史状态。我的解决方案在 roadmap 里：
- 给 fact 加**时效标签**（`valid_until`、`confidence_decay`）；
- 覆盖不是删除，而是把旧事实移到 `archived` 区，检索时按时间窗口加权；
- Notetaker 在 upsert 前做**意图检测**，区分'永久更新'和'临时例外'。

这需要更复杂的 schema，但原则不变：显式治理优于隐式堆积。"

### Q3："7B 模型跑 88.71% 是不是只在特定 benchmark 上有效？泛化性怎么保证？"

**答**："所以我跑了**三个不同性质的 benchmark** 做 triangulation：
- LV-Eval 测** adversarial 长文档事实召回**；
- NoLiMa 测**多文档 needle-in-haystack + distractor**；
- LongMemEval 测**多轮对话记忆**。

三个场景的提升都很大，说明这不是过拟合某一个数据集。另外我有 external generalization 检查：在 BAMBOO 上做 holdout 验证，确保 tuned on A、tested on B 仍然有效。"

### Q4："你接触大模型才 3 个月，怎么保证你不是在搭积木？"

**答**："3 个月是接触大模型的时间，但我的工程经验不止 3 个月。MASE 里体现的不是'我懂很多 LLM 论文'，而是**工程判断**：
- 为什么不用向量数据库？——因为我在调试时发现黑盒记忆不可定位；
- 为什么做 anti-overfit policy？——因为我在跑 benchmark 时发现自己会下意识 cherry-pick 好结果，所以用 CI 和文档约束自己；
- 为什么用 Pydantic + SQLite + Markdown？——因为我相信 Agent 记忆最终要对人负责，而不仅仅是让模型更聪明。

这些决策不需要 3 年 LLM 经验，需要的是**对系统复杂度的敬畏**。"

### Q5："如果让你锐评 Kimi 当前的 Agent 能力，你会说什么？"

**答**（建设性批评）："Kimi 的长上下文窗口和工具调用能力已经是第一梯队。但如果从 MASE 的视角看，我觉得可以补强两点：

1. **记忆治理层**：当前的多轮对话记忆更像是'上下文拼接'，随着轮数增加噪声会累积。可以考虑引入显式的 Entity Fact Sheet 机制，在后台主动做记忆压缩和冲突消解，而不是依赖模型自己从长上下文里提炼。

2. **Adaptive Verification**：在工具调用链较长时（比如'查天气→查路线→订餐厅'），中间步骤的错误会级联放大。可以在 Planner 和 Executor 之间加一层轻量级 verifier，根据 retrieval confidence 决定是否二次确认，而不是每条都问用户。

这两点都不需要换更大的模型，是纯工程层面的优化。"

### Q6："你的代码里最能体现'品味'的是哪一段？"

**答**："我会展示 `src/mase/protocol.py` 里的 `AgentMessage`：

```python
@dataclass(frozen=True)
class AgentMessage:
    kind: str
    source: str
    target: str
    payload: dict[str, Any]
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)
```

为什么这样设计？
- **frozen=True**：消息一旦发出就不可变，防止下游节点偷偷改 payload，导致调试时抓狂；
- **default_factory**：避免可变默认参数的 Python 经典坑；
- **UTC isoformat**：时间戳不带时区歧义，日志对齐时不会出错。

这段代码做的事情很简单，但它体现了我的一个原则：**在 Agent 系统里，消息协议是宪法，宪法必须严格、不可变、无歧义。**"

### Q7："MASE 和 MemGPT 有什么区别？"

**答**："MemGPT 做的是'虚拟上下文管理'——把超出窗口的内容换进换出，但记忆语义仍然是黑盒的。MASE 做的是**存储层语义重构**——记忆不是模型的附属品，而是独立的、可审计的、可治理的工程对象。

打个比方：MemGPT 是给模型配了一个更大的虚拟内存条；MASE 是给 Agent 配了一个数据库 + 审计日志 + 版本控制。"

### Q8："如果让你带一个实习生继续开发 MASE，你会让他先做什么？"

**答**："我会让他先跑 benchmark，但不要改代码——让他先读 `BENCHMARK_ANTI_OVERFIT.md` 和三个 claim manifest，理解什么叫'诚实的数字'。

然后让他挑一个 LongMemEval 里 MASE 做失败的 case，手动打开 SQLite 和 Markdown，看看到底是 retrieval 漏了、fact extraction 错了、还是 planner 分解有问题。

这个练习的目的不是 fix bug，是建立直觉：**Agent 的问题最终都要定位到记忆层的某个具体行**。"

---

## 四、现场演示建议（如果面试官说"给我看看"）

### Option 1：跑 CLI（3 分钟）
```bash
python mase_cli.py
# 输入："我上周说预算 5000，现在改成 8000"
# 然后问："我的预算是多少？"
# 最后打开 memory/ 目录下的 Markdown，展示 Entity Fact Sheet 被覆盖的过程
```

### Option 2：跑 Benchmark Audit（2 分钟）
```bash
python scripts/audit_anti_overfit.py --strict
python scripts/audit_repo_hygiene.py
```
展示 CI  gate 是怎么拦截不诚实数字的。

### Option 3：Code Walkthrough（5 分钟）
按这个顺序打开文件：
1. `docs/ARCHITECTURE_BOUNDARIES.md` —— 展示你对 stable/experimental surface 的思考；
2. `benchmarks/runner.py` 的 `run_case()` —— 展示 per-case isolation；
3. `src/mase/protocol.py` —— 展示消息协议设计；
4. `docs/BENCHMARK_ANTI_OVERFIT.md` —— 展示工程纪律。

---

## 五、心态提示

1. **不要谦虚过头**：README 里写"接触大模型仅 3 个月的新手"是真诚，但面试时是减分项。你可以说"我系统接触 LLM 工程是近几个月，但我的工程判断来自更长期的系统开发经验"。

2. **主动暴露边界**：当聊到同义词泛化、高并发、大规模文档召回时，主动说"这是当前 admitted 的边界，我的 roadmap 是..."——这比被问出来再辩解要加分得多。

3. **把 MASE 当成方法论，不是产品**：面试官可能问"MASE 开源了吗？star 多少？"如果数据不好看，立刻 pivot："MASE 的价值不是作为独立产品，而是作为我验证 Agent 记忆假设的实验平台。我在这个项目里验证的 eval hygiene、架构边界、记忆治理方法论，可以直接迁移到 Kimi 的 Agent 内核开发中。"

---

*祝面试顺利。记住：你不是在推销 MASE，你是在推销你通过 MASE 证明的 Engineering Judgment。*
