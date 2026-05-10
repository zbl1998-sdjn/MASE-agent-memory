# MASE 7 天冲刺学习计划（大白话版）

> ⚠️ **Kimi 生成文件（审核重写版）**：本文件由 Kimi 逐行审核后重写，所有英文术语都加了中文翻译。
> 🎯 **目标**：7 天后能流利讲项目、应对技术面试、展示代码级理解。
> 📌 **前提**：你已有桌面学习计划（15 模块）作为骨架，本计划是压缩版执行手册。

---

## 先搞懂这些英文词（不然读不下去）

| 英文 | 中文意思 | 大白话解释 |
|------|---------|-----------|
| **fallback** | 兜底/回退 | 主方案挂了，备用方案顶上 |
| **schema** | 表结构/结构定义 | 数据库里的表长什么样，有哪些字段 |
| **handler** | 处理函数 | 收到指令后，具体干活的函数 |
| **fast-path** | 快速通道 | 不走复杂流程，直接抄近路 |
| **env（environment variable）** | 环境变量 | 程序外面的开关，改它不用改代码 |
| **ablation** | 消融实验 | 把某个功能关掉，看分数掉多少，证明这功能有用 |
| **smoke test** | 冒烟测试 | 最简单的快速测试，确认东西能跑，没"冒烟"（没坏） |
| **assertion** | 断言 | 代码里写的"这里必须是真"，否则测试失败 |
| **chunk** | 文本块 | 把长文章切成一小段一小段 |
| **rerank** | 重排序 | 先粗筛一堆候选，再用更精细的模型重新打分排序 |
| **embedding** | 嵌入向量 | 把文字转成一串数字，让计算机能算"相似度" |
| **tokenizer** | 分词器 | 把句子切成一个个词或字，算 token 数量 |
| **WAL** | 预写日志 | SQLite 的防崩机制，先写日志再写数据，崩了能恢复 |
| **CRUD** | 增删改查 | 创建(Create)、读取(Read)、更新(Update)、删除(Delete) |
| **payload** | 载荷/数据内容 | 消息里真正携带的数据 |
| **side-effect** | 副作用 | 函数做了不该做的事，比如偷偷改了全局状态 |
| **gated by env** | 由环境变量控制开关 | 默认关，设 env=1 才开 |
| **degrade gracefully** | 优雅降级 | 主功能挂了，系统不崩，只是效果变差 |
| **pub/sub** | 发布订阅 | 一个人广播消息，多个听众各自接收，互相不认识 |
| **fire-and-forget** | 发完就忘 | 发出消息不等回复，不管对方收没收到 |
| **frozen** | 冻结的/不可变的 | 创建后不能修改，像 const |
| **dataclass** | 数据类 | Python 里专门用来存数据的类，自动生成构造函数 |
| **LLM hop** | LLM 调用次数 | 每调用一次大模型，算一个 hop |
| **holdout** | 留出集 | 专门留出来测试的数据，不能用来调参 |
| **distractor** | 干扰项 |  benchmark 里故意塞进去的假信息，测试模型会不会被骗 |
| **top-k** | 前 k 个 | 分数最高的前 k 个结果 |
| **O(n)** | 时间复杂度（与 n 成正比） | 数据量翻一倍，耗时也大约翻一倍 |

---

## 学习原则（每天 4-6 小时）

1. **早上 2 小时**：读源码（只看本计划指定的文件和行号）
2. **下午 2 小时**：跑实验（跑 example、改 env 变量、看结果）
3. **晚上 1-2 小时**：背话术（用 `INTERVIEW_CHEATSHEET_大白话版.md` 自测）

**绝不做的事**：
- 不读完整文件（只看关键函数）
- 不读无关模块（EventBus/MCP/Frontend 延后）
- 不写新代码（只读、只跑、只改 env 开关）

---

## Day 1：双白盒理念 + 存储层（地基日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `README.md` | 1-70 | 核心数据、双白盒定义 |
| `docs/ARCHITECTURE_BOUNDARIES.md` | 全文 | 稳定面/实验面/本地面 三层边界 |
| `mase_tools/memory/db_core.py` | 1-200 | SQLite 表结构（schema）、连接池、`_ensure_schema`（确保表结构已创建） |
| `mase_tools/memory/db_core.py` | 搜 `CREATE TABLE` | events（事件流水表）/ entity_state（实体事实表）/ session_context（会话上下文表） |

### 下午：跑实验（2h）
- [ ] `pip install -e ".[dev]"`（用开发模式安装，改代码不用重装）
- [ ] `python mase_cli.py`，输入："我叫张三，预算 5000"
- [ ] 同一对话再问："我预算多少？" → 确认记住（跨轮记忆）
- [ ] 打开 `memory/index.db` 用 DB Browser（数据库浏览器）或 `sqlite3` 命令行看表结构
- [ ] 执行 `.schema`（显示所有表结构），拍照/截图保存

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET_大白话版.md` 第 1 题："为什么不用向量数据库？"
- [ ] 背熟 `INTERVIEW_CHEATSHEET_大白话版.md` 第 9 题："你怎么保证没刷榜？"

---

## Day 2：Entity Fact Sheet（实体事实卡）+ 冲突治理（核心日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `mase_tools/memory/api.py` | 40-128 | `mase2_upsert_fact`（覆盖式写入事实）、`mase2_supersede_facts`（批量标记旧事实失效）、`mase2_correct_and_log`（纠正并记录） |
| `mase_tools/memory/correction_detector.py` | 全文 | 纠正触发词正则表达式、`_TRIGGER_PATTERNS`（触发模式）、`_STRIP_PATTERNS`（去触发词保留主题词） |
| `src/mase/fact_sheet.py` | 全文 | `build_long_context_fact_sheet`（构建长上下文事实表）、三档配置（长记忆/多文档/单文档） |

### 下午：跑实验（2h）
- [ ] 在 CLI 说："我喜欢川菜" → 确认写入
- [ ] 再说："不对，我说错了，我喜欢粤菜" → 触发纠正检测（correction detection）
- [ ] 查 SQLite：`SELECT * FROM entity_state WHERE key LIKE '%口味%';`
- [ ] 确认旧值被覆盖，不是追加（append-only）
- [ ] 打开 `mase_tools/memory/db_core.py`，搜 `upsert_entity_fact` 的 SQL 实现

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET_大白话版.md` 第 2 题："冲突事实怎么处理？"
- [ ] 能说出 `supersede`（取代/使失效）和 `upsert`（覆盖插入）的区别

---

## Day 3：Router（路由）+ Notetaker（记事员）（管道日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `src/mase/router.py` | 43-117 | `MEMORY_TRIGGER_PHRASES`（记忆触发短语）、`keyword_router_decision`（关键词路由决策）、`ROUTER_SYSTEM`（路由系统提示词） |
| `src/mase/notetaker_agent.py` | 32-120 | `NOTETAKER_SYSTEM`（记事员系统提示词）、`NOTETAKER_TOOLS`（4个工具定义）、`_TRI_VAULT_BUCKET_BY_TOOL`（三仓映射表） |
| `src/mase/langgraph_orchestrator.py` | 39-120 | `AgentState`（智能体状态，7个键）、`router_node`（路由节点）、fast path 逻辑 |

### 下午：跑实验（2h）
- [ ] 在 CLI 分别输入以下问题，观察是否触发记忆检索：
  - "你好" → 应走 direct_answer（直接回答，不查记忆）
  - "我上次说的预算" → 应走 search_memory（搜索记忆）
  - "那个方案怎么样" → 可能误触发（false positive），观察结果
- [ ] 设 `MASE_ORCHESTRATOR_FAST=1`（走快速通道），对比响应速度
- [ ] 设 `MASE_ORCHESTRATOR_FAST=0`（走 LLM 路由），对比路由精度

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET_大白话版.md` 第 3 题："Router 为什么保留 keyword fast-path（关键词快速通道）？"
- [ ] 能解释 `AgentState`（智能体状态字典）的 7 个键分别存什么

---

## Day 4：Planner（计划员）+ Executor（执行器）+ Fact Sheet 压缩（长上下文日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `src/mase/planner_agent.py` | 全文 | `PLANNER_SYSTEM`（计划员系统提示词）、≤4 步限制、fallback（兜底）逻辑 |
| `src/mase/executor.py` | 全文 | system prompt（系统提示词）、honesty（诚实）设计 |
| `src/mase/fact_sheet_long_memory.py` | 全文 | `build_long_memory_full_fact_sheet`（构建长记忆完整事实表）、char_budget（字符预算）、local_only（仅本地模式）分支 |
| `src/mase/mode_selector.py` | 60-80 | `long_context_search_limit`（长上下文搜索限制）、`long_context_window_radius`（长上下文窗口半径）长度桶映射 |

### 下午：跑实验（2h）
- [ ] 读 `examples/04_long_doc_qa_256k.py` 逻辑（长文档问答，256k 上下文）
- [ ] 修改 `config.json` 里的 length bucket（长度桶），观察 search_limit 变化
- [ ] 打印 fact_sheet 长度：`len(fact_sheet)`，确认它远小于原始文本

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET_大白话版.md` 第 4 题："256k 怎么做到 88%？"
- [ ] 能手写公式：`score = 0.5*dense + 0.3*BM25 + 0.2*temporal`

---

## Day 5：Hybrid Recall（混合召回）+ Multi-pass（多轮检索）（检索日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `src/mase/hybrid_recall.py` | 1-60 | 三路公式、temporal cues（时间线索词）、权重 env 覆盖 |
| `src/mase/hybrid_recall.py` | 117-150 | `_InlineBM25`（内联 BM25，纯 Python 实现）、IDF 公式、tokenize（分词） |
| `src/mase/multipass_retrieval.py` | 1-50 | 五阶段管道定义、env 开关 |
| `src/mase/multipass_retrieval.py` | 86-147 | query rewrite cache（查询改写缓存）、HyDE cache（假设文档嵌入缓存） |

### 下午：跑实验（2h）
- [ ] `set MASE_HYBRID_RECALL=1`（打开混合召回），跑长文档 QA，对比召回质量
- [ ] `set MASE_MULTIPASS=1`（打开多轮检索），观察延迟变化（应该会慢）
- [ ] `set MASE_HYBRID_RECALL_WEIGHTS=0.7,0.2,0.1`（改权重），观察结果变化
- [ ] 记录结论：哪种权重组合在你的场景下最好？

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET_大白话版.md` 第 5 题："HyDE 会不会引入幻觉（hallucination，编造不存在的信息）？"
- [ ] 能解释 safety net（安全网/兜底机制）的作用

---

## Day 6：Model Interface（模型接口）+ 熔断 + Benchmark 评测（工程日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `src/mase/model_interface.py` | 1-120 | 多后端支持、config 解析链、cloud policy（云模型策略，默认阻止） |
| `src/mase/health_tracker.py` | 1-107 | `CandidateHealth`（候选健康状态）、EWMA（指数加权移动平均）、cooldown（冷却）逻辑 |
| `src/mase/circuit_breaker.py` | 全文 | `BreakerState`（熔断器状态）、closed（闭合）/open（断开）/half_open（半开）转换 |
| `benchmarks/llm_judge.py` | 全文 | judge system prompt（评委系统提示词）、只升级不降级策略 |

### 下午：跑实验（2h）
- [ ] `python -m pytest tests/ -q`，确认 383/383 passing（全部通过）
- [ ] 挑 3 个测试名有趣的 case，读它们的 assertion（断言）逻辑
- [ ] 跑 benchmark smoke 样本（冒烟测试，小数据集），打开 result JSON 看结构
- [ ] `set MASE_ALLOW_CLOUD_MODELS=1`（允许云模型），观察 cloud policy 是否生效

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET_大白话版.md` 第 6 题："模型挂了怎么办？"
- [ ] 背熟 `INTERVIEW_CHEATSHEET_大白话版.md` 第 7 题："84.8% 是必然还是偶然？"

---

## Day 7：整合 + 模拟面试（决战日）

### 上午：整合（2h）
- [ ] 打开 `CODE_MAP_大白话版.md`，逐文件过一遍
- [ ] 画一张 A4 纸：Router→Notetaker→Planner→Executor 时序图（按时间顺序画的流程图）
- [ ] 列出你会 show off（展示/炫技）的 3 个代码片段（建议：protocol.py frozen dataclass、hybrid_recall.py 三路融合、llm_judge.py 保守策略）

### 下午：模拟面试（2h）
找朋友或录音，完成以下：
- [ ] 5 分钟快速版（不看稿）
- [ ] 10 个灵魂追问，每个回答 1-2 分钟
- [ ] 现场打开代码，指给"面试官"看 3 个关键实现

### 晚上：查漏补缺（1-2h）
- [ ] 复习桌面学习计划里的"错误手册"TOP 15 报错
- [ ] 复习桌面学习计划里的"知识手册"对比表
- [ ] 确认 `README.md` 里的 clone URL 已修正（`MASE-agent-memory.git`）
- [ ] 确认本地修改已 push（推送到远程仓库，如果你打算投简历）

---

## 如果只有 5 天怎么办？

砍掉 Day 5 的部分实验和 Day 6 的部分源码阅读，保留：
- Day 1-3：必须完整执行（理念+存储+管道）
- Day 4：只看 planner/executor/fact_sheet，不跑 256k 实验
- Day 5：只看 hybrid_recall.py 公式，不跑 multipass
- Day 6-7：合并为 1 天，只背 `INTERVIEW_CHEATSHEET_大白话版.md` 的 10 道题

---

## 每天结束时的自检三问

1. **我今天打开了几行源码？**（目标：≥100 行）
2. **我能不看文档说出今天学的模块是做什么的吗？**（目标：能）
3. **如果面试官问我"为什么这样设计"，我能答到代码级别吗？**（目标：能指出行号）

如果任何一题答案为"否"，当天晚上必须补课，不能拖到第二天。

---

> **Kimi 备注**：本计划假设你每天有 4-6 小时投入。如果时间更少，建议直接跳到 Day 7 的模拟面试，用 `INTERVIEW_CHEATSHEET_大白话版.md` 和 `CODE_MAP_大白话版.md` 临时抱佛脚。
