# MASE 7 天冲刺学习计划

> ⚠️ **Kimi 生成文件**：本文件由 Kimi 根据源码深度分析生成，配合桌面学习计划使用。
> 🎯 **目标**：7 天后能流利讲项目、应对技术面试、展示代码级理解。
> 📌 **前提**：你已有桌面学习计划（15 模块）作为骨架，本计划是压缩版执行手册。

---

## 学习原则（每天 4-6 小时）

1. **早上 2 小时**：读源码（只看本计划指定的文件和行号）
2. **下午 2 小时**：跑实验（跑 example、改 env 变量、看结果）
3. **晚上 1-2 小时**：背话术（用 `INTERVIEW_CHEATSHEET.md` 自测）

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
| `docs/ARCHITECTURE_BOUNDARIES.md` | 全文 | Stable/Experimental/Local 三层边界 |
| `mase_tools/memory/db_core.py` | 1-200 | SQLite schema、连接池、`_ensure_schema` |
| `mase_tools/memory/db_core.py` | 搜 `CREATE TABLE` | events / entity_state / session_context 表结构 |

### 下午：跑实验（2h）
- [ ] `pip install -e ".[dev]"`
- [ ] `python mase_cli.py`，输入："我叫张三，预算 5000"
- [ ] 同一对话再问："我预算多少？" → 确认记住
- [ ] 打开 `memory/index.db` 用 DB Browser 或 `sqlite3` 命令行看表结构
- [ ] 执行 `.schema`，拍照/截图保存

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET.md` 第 1 题："为什么不用向量数据库？"
- [ ] 背熟 `INTERVIEW_CHEATSHEET.md` 第 9 题："你怎么保证没刷榜？"

---

## Day 2：Entity Fact Sheet + 冲突治理（核心日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `mase_tools/memory/api.py` | 40-128 | `mase2_upsert_fact`、`mase2_supersede_facts`、`mase2_correct_and_log` |
| `mase_tools/memory/correction_detector.py` | 全文 | 纠正触发词正则、`_TRIGGER_PATTERNS`、`_STRIP_PATTERNS` |
| `src/mase/fact_sheet.py` | 全文 | `build_long_context_fact_sheet`、三档配置 |

### 下午：跑实验（2h）
- [ ] 在 CLI 说："我喜欢川菜" → 确认写入
- [ ] 再说："不对，我说错了，我喜欢粤菜" → 触发纠正检测
- [ ] 查 SQLite：`SELECT * FROM entity_state WHERE key LIKE '%口味%';`
- [ ] 确认旧值被覆盖，不是追加
- [ ] 打开 `mase_tools/memory/db_core.py`，搜 `upsert_entity_fact` 的 SQL 实现

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET.md` 第 2 题："冲突事实怎么处理？"
- [ ] 能说出 `supersede` 和 `upsert` 的区别

---

## Day 3：Router + Notetaker（管道日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `src/mase/router.py` | 43-117 | `MEMORY_TRIGGER_PHRASES`、`keyword_router_decision`、`ROUTER_SYSTEM` |
| `src/mase/notetaker_agent.py` | 32-120 | `NOTETAKER_SYSTEM`、`NOTETAKER_TOOLS`、`_TRI_VAULT_BUCKET_BY_TOOL` |
| `src/mase/langgraph_orchestrator.py` | 39-120 | `AgentState`、`router_node`、fast path 逻辑 |

### 下午：跑实验（2h）
- [ ] 在 CLI 分别输入以下问题，观察是否触发记忆检索：
  - "你好" → 应走 direct_answer
  - "我上次说的预算" → 应走 search_memory
  - "那个方案怎么样" → 可能误触发，观察结果
- [ ] 设 `MASE_ORCHESTRATOR_FAST=1`，对比响应速度
- [ ] 设 `MASE_ORCHESTRATOR_FAST=0`，对比路由精度

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET.md` 第 3 题："Router 为什么保留 keyword fast-path？"
- [ ] 能解释 `AgentState` 的 7 个键分别存什么

---

## Day 4：Planner + Executor + Fact Sheet 压缩（长上下文日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `src/mase/planner_agent.py` | 全文 | `PLANNER_SYSTEM`、≤4 步限制、fallback 逻辑 |
| `src/mase/executor.py` | 全文 | system prompt、honesty 设计 |
| `src/mase/fact_sheet_long_memory.py` | 全文 | `build_long_memory_full_fact_sheet`、char_budget、local_only 分支 |
| `src/mase/mode_selector.py` | 60-80 | `long_context_search_limit`、`long_context_window_radius` 长度桶映射 |

### 下午：跑实验（2h）
- [ ] 跑 `examples/04_long_doc_qa_256k.py`（或看里面逻辑）
- [ ] 修改 `config.json` 里的 length bucket，观察 search_limit 变化
- [ ] 打印 fact_sheet 长度：`len(fact_sheet)`，确认它远小于原始文本

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET.md` 第 4 题："256k 怎么做到 88%？"
- [ ] 能手写公式：`score = 0.5*dense + 0.3*BM25 + 0.2*temporal`

---

## Day 5：Hybrid Recall + Multi-pass（检索日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `src/mase/hybrid_recall.py` | 1-60 | 三路公式、temporal cues、权重 env 覆盖 |
| `src/mase/hybrid_recall.py` | 117-150 | `_InlineBM25`、IDF 公式、tokenize |
| `src/mase/multipass_retrieval.py` | 1-50 | 五阶段管道定义、env 开关 |
| `src/mase/multipass_retrieval.py` | 86-147 | query rewrite cache、HyDE cache |

### 下午：跑实验（2h）
- [ ] `set MASE_HYBRID_RECALL=1`，跑长文档 QA，对比召回质量
- [ ] `set MASE_MULTIPASS=1`，观察延迟变化（应该会慢）
- [ ] 改 `MASE_HYBRID_RECALL_WEIGHTS=0.7,0.2,0.1`，观察结果变化
- [ ] 记录结论：哪种权重组合在你的场景下最好？

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET.md` 第 5 题："HyDE 会不会引入幻觉？"
- [ ] 能解释 safety net 的作用

---

## Day 6：Model Interface + 熔断 + Benchmark 评测（工程日）

### 上午：读代码（2h）
| 文件 | 行号范围 | 看什么 |
|------|---------|--------|
| `src/mase/model_interface.py` | 1-120 | 多后端支持、config 解析链、cloud policy |
| `src/mase/health_tracker.py` | 1-107 | `CandidateHealth`、EWMA、cooldown 逻辑 |
| `src/mase/circuit_breaker.py` | 全文 | `BreakerState`、closed/open/half_open 转换 |
| `benchmarks/llm_judge.py` | 全文 | judge system prompt、只升级不降级策略 |

### 下午：跑实验（2h）
- [ ] `python -m pytest tests/ -q`，确认 383/383 passing
- [ ] 挑 3 个测试名有趣的 case，读它们的断言逻辑
- [ ] 跑 benchmark smoke 样本（小数据集），打开 result JSON 看结构
- [ ] 设 `MASE_ALLOW_CLOUD_MODELS=1`，观察 cloud policy 是否生效

### 晚上：背话术（1h）
- [ ] 背熟 `INTERVIEW_CHEATSHEET.md` 第 6 题："模型挂了怎么办？"
- [ ] 背熟 `INTERVIEW_CHEATSHEET.md` 第 7 题："84.8% 是必然还是偶然？"

---

## Day 7：整合 + 模拟面试（决战日）

### 上午：整合（2h）
- [ ] 打开 `CODE_MAP.md`，逐文件过一遍，确认每个文件的作用
- [ ] 画一张 A4 纸：Router→Notetaker→Planner→Executor 时序图
- [ ] 列出你会 show off 的 3 个代码片段（建议：protocol.py frozen dataclass、hybrid_recall.py 三路融合、llm_judge.py 保守策略）

### 下午：模拟面试（2h）
找朋友或录音，完成以下：
- [ ] 5 分钟快速版（不看稿）
- [ ] 10 个灵魂追问，每个回答 1-2 分钟
- [ ] 现场打开代码，指给"面试官"看 3 个关键实现

### 晚上：查漏补缺（1-2h）
- [ ] 复习 `错误手册.md` 里的 TOP 15 报错
- [ ] 复习 `知识手册.md` 里的对比表
- [ ] 确认 `README.md` 里的 clone URL 已修正（`MASE-agent-memory.git`）
- [ ] 确认本地修改已 push（如果你打算投简历）

---

## 如果只有 5 天怎么办？

砍掉 Day 5 的部分实验和 Day 6 的部分源码阅读，保留：
- Day 1-3：必须完整执行（理念+存储+管道）
- Day 4：只看 planner/executor/fact_sheet，不跑 256k 实验
- Day 5：只看 hybrid_recall.py 公式，不跑 multipass
- Day 6-7：合并为 1 天，只背 `INTERVIEW_CHEATSHEET.md` 的 10 道题

---

## 每天结束时的自检三问

1. **我今天打开了几行源码？**（目标：≥100 行）
2. **我能不看文档说出今天学的模块是做什么的吗？**（目标：能）
3. **如果面试官问我"为什么这样设计"，我能答到代码级别吗？**（目标：能指出行号）

如果任何一题答案为"否"，当天晚上必须补课，不能拖到第二天。

---

> **Kimi 备注**：本计划假设你每天有 4-6 小时投入。如果时间更少，建议直接跳到 Day 7 的模拟面试，用 `INTERVIEW_CHEATSHEET.md` 和 `CODE_MAP.md` 临时抱佛脚。
