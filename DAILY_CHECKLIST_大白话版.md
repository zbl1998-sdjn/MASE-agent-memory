# MASE 7 天冲刺每日打卡清单（大白话版）

> ⚠️ **Kimi 生成文件（审核重写版）**：配合 `7DAY_SPRINT_PLAN_大白话版.md` 使用，每天完成一项勾一项。所有英文术语都加了中文翻译。

---

## 先搞懂这些英文词（不然读不下去）

| 英文 | 中文意思 | 大白话解释 |
|------|---------|-----------|
| **env** | 环境变量 | 程序外面的开关，改它不用改代码 |
| **fallback** | 兜底/回退 | 主方案挂了，备用方案顶上 |
| **schema** | 表结构 | 数据库里的表长什么样，有哪些字段 |
| **handler** | 处理函数 | 收到指令后，具体干活的函数 |
| **fast-path** | 快速通道 | 不走复杂流程，直接抄近路 |
| **ablation** | 消融实验 | 把某个功能关掉，看分数掉多少 |
| **smoke test** | 冒烟测试 | 最简单的快速测试，确认东西能跑 |
| **assertion** | 断言 | 代码里写的"这里必须是真"，否则测试失败 |
| **chunk** | 文本块 | 把长文章切成一小段一小段 |
| **cross-encoder** | 交叉编码器 | 一种模型，把问题和答案拼在一起打分 |
| **embedding** | 嵌入向量 | 把文字转成一串数字，让计算机能算相似度 |
| **tokenizer** | 分词器 | 把句子切成一个个词或字 |
| **WAL** | 预写日志 | SQLite 的防崩机制，崩了能恢复 |
| **CRUD** | 增删改查 | 创建、读取、更新、删除 |
| **EWMA** | 指数加权移动平均 | 越新的数据权重越高 |
| **cooldown** | 冷却时间 | 失败后暂停一段时间，不再尝试 |
| **half-open** | 半开状态 | 熔断器里放少量请求试探是否恢复 |
| **verifier** | 校验器 | 另一个模型，检查主模型答案对不对 |
| **LLM hop** | LLM 调用次数 | 每调用一次大模型，算一个 hop |
| **holdout** | 留出集 | 专门留出来测试的数据，不能用来调参 |
| **distractor** | 干扰项 | benchmark 里故意塞进去的假信息 |
| **top-k** | 前 k 个 | 分数最高的前 k 个结果 |
| **O(n)** | 时间复杂度 | 数据量翻一倍，耗时也大约翻一倍 |
| **append-only** | 只追加 | 只能往后面加，不能改旧的 |
| **supersede** | 取代/使失效 | 新事实来了，旧事实标记为失效 |
| **upsert** | 覆盖插入 | 有就更新，没有就插入 |

---

## Day 1：双白盒理念 + 存储层

### 上午：读代码
- [ ] 读完 `README.md` 前 70 行，记住三个 benchmark（基准测试）数字
- [ ] 读完 `docs/ARCHITECTURE_BOUNDARIES.md`（架构边界文档）
- [ ] 读完 `mase_tools/memory/db_core.py` 前 200 行（SQLite 核心，数据库操作）
- [ ] 在 `db_core.py` 里找到 `CREATE TABLE` 语句，确认 events（事件流水表）/ entity_state（实体状态表）表结构

### 下午：跑实验
- [ ] `pip install -e ".[dev]"` 成功（开发模式安装，改代码不用重装）
- [ ] `python mase_cli.py` 跑起来（MASE 命令行界面）
- [ ] 输入："我叫张三，预算 5000" → 确认记住
- [ ] 同一对话再问："我预算多少？" → 确认跨轮记忆（跨会话记忆）
- [ ] 用 `sqlite3` 或 DB Browser（数据库浏览器）打开 `memory/index.db`，执行 `.schema`（显示所有表结构）

### 晚上：背话术
- [ ] 能不看稿说出"为什么不用向量数据库"（2 分钟版本）
- [ ] 能不看稿说出"怎么保证没刷榜"（2 分钟版本）

**今日验收标准**：能打开 SQLite schema（表结构）并指出 entity_state（实体状态表）的主键和覆盖语义。

---

## Day 2：Entity Fact Sheet（实体事实卡）+ 冲突治理

### 上午：读代码
- [ ] 读完 `mase_tools/memory/api.py` 第 40-128 行（API 接口层，记忆操作入口）
- [ ] 读完 `mase_tools/memory/correction_detector.py` 全文（纠正检测器，检测"我说错了"）
- [ ] 读完 `src/mase/fact_sheet.py` 全文（事实表构建，长上下文压缩）

### 下午：跑实验
- [ ] CLI（命令行界面）说："我喜欢川菜" → 确认写入
- [ ] CLI 说："不对，我说错了，我喜欢粤菜" → 观察纠正检测（correction detection）
- [ ] 查 SQLite：`SELECT * FROM entity_state WHERE key LIKE '%口味%';`
- [ ] 确认旧值被覆盖，不是追加（append-only，只追加）
- [ ] 找到 `db_core.py` 里 `upsert_entity_fact` 的 SQL 实现

### 晚上：背话术
- [ ] 能解释 `supersede`（取代/使失效）和 `upsert`（覆盖插入）的区别
- [ ] 能说出纠正检测的 3 个中文触发词

**今日验收标准**：能在 CLI 演示"事实覆盖"过程，并用 SQL 验证。

---

## Day 3：Router（路由器）+ Notetaker（记事员）

### 上午：读代码
- [ ] 读完 `src/mase/router.py` 第 43-117 行（路由决策，判断要不要查记忆）
- [ ] 读完 `src/mase/notetaker_agent.py` 第 32-120 行（记事智能体，唯一有写权限）
- [ ] 读完 `src/mase/langgraph_orchestrator.py` 第 39-120 行（LangGraph 编排器，状态机）

### 下午：跑实验
- [ ] 输入"你好" → 确认走 direct_answer（直接回答，不查记忆）
- [ ] 输入"我上次说的预算" → 确认走 search_memory（搜索记忆）
- [ ] 输入"那个方案怎么样" → 观察是否误触发（false positive，假阳性/误报）
- [ ] `set MASE_ORCHESTRATOR_FAST=1`（走快速通道），对比速度
- [ ] `set MASE_ORCHESTRATOR_FAST=0`（走 LLM 路由），对比精度

### 晚上：背话术
- [ ] 能解释 keyword fast-path（关键词快速通道）的三个保留原因（延迟/成本/可靠性）
- [ ] 能说出 `AgentState`（智能体状态字典）的 7 个键

**今日验收标准**：能解释 Router 的双路径设计，并演示 fast path 的开关效果。

---

## Day 4：Planner（计划员）+ Executor（执行器）+ Fact Sheet 压缩

### 上午：读代码
- [ ] 读完 `src/mase/planner_agent.py` 全文（任务分解，≤4步）
- [ ] 读完 `src/mase/executor.py` 全文（最终回答生成）
- [ ] 读完 `src/mase/fact_sheet_long_memory.py` 全文（长记忆专用事实表）
- [ ] 读完 `src/mase/mode_selector.py` 第 60-80 行（模式选择器，长度桶映射）

### 下午：跑实验
- [ ] 读 `examples/04_long_doc_qa_256k.py` 逻辑（长文档问答，256k 上下文）
- [ ] 修改 `config.json` 里的 length bucket（长度桶），观察 search_limit（搜索限制）变化
- [ ] 打印 fact_sheet（事实表）长度：`len(fact_sheet)`，确认远小于原始文本

### 晚上：背话术
- [ ] 能手写三路融合公式：`score = 0.5*dense + 0.3*BM25 + 0.2*temporal`
- [ ] 能解释 Planner 为什么限制 ≤4 步

**今日验收标准**：能解释 256k→~16k 的压缩路径，并指出 `window_radius`（窗口半径）的数值。

---

## Day 5：Hybrid Recall（混合召回）+ Multi-pass（多轮检索）

### 上午：读代码
- [ ] 读完 `src/mase/hybrid_recall.py` 第 1-150 行（BM25+Dense+Temporal 三路融合）
- [ ] 读完 `src/mase/multipass_retrieval.py` 第 1-50 行（多轮检索，五阶段管道）
- [ ] 读完 `src/mase/multipass_retrieval.py` 第 86-147 行（query rewrite 查询改写缓存、HyDE 缓存）

### 下午：跑实验
- [ ] `set MASE_HYBRID_RECALL=1`（打开混合召回），跑长文档 QA，对比召回质量
- [ ] `set MASE_MULTIPASS=1`（打开多轮检索），观察延迟变化（应该会慢）
- [ ] `set MASE_HYBRID_RECALL_WEIGHTS=0.7,0.2,0.1`（改权重），观察结果变化
- [ ] 记录结论：哪种权重组合在你的场景下最好？

### 晚上：背话术
- [ ] 能解释 HyDE（假设文档嵌入）的作用和风险
- [ ] 能解释 safety net（安全网/兜底机制）的作用

**今日验收标准**：能调 env 变量做一次小消融实验（ablation），并给出结论。

---

## Day 6：Model Interface（模型接口）+ 熔断 + Benchmark（基准测试）

### 上午：读代码
- [ ] 读完 `src/mase/model_interface.py` 第 1-120 行（多后端支持、cloud policy 云模型策略）
- [ ] 读完 `src/mase/health_tracker.py` 第 1-107 行（健康追踪、EWMA 指数加权移动平均、cooldown 冷却）
- [ ] 读完 `src/mase/circuit_breaker.py` 全文（熔断器、closed/open/half_open 三态）
- [ ] 读完 `benchmarks/llm_judge.py` 全文（LLM 评委、只升级不降级策略）

### 下午：跑实验
- [ ] `python -m pytest tests/ -q` → 确认 383/383 passing（全部通过）
- [ ] 挑 3 个测试名有趣的 case，读它们的 assertion（断言）逻辑
- [ ] 跑 benchmark smoke 样本（冒烟测试，小数据集），打开 result JSON 看结构
- [ ] `set MASE_ALLOW_CLOUD_MODELS=1`（允许云模型），观察 cloud policy 是否生效

### 晚上：背话术
- [ ] 能解释 EWMA 0.3 的含义（新样本权重 30%）
- [ ] 能画熔断状态转换图（closed 闭合 → open 断开 → half_open 半开）
- [ ] 能解释 LLM judge "只升级不降级"的策略

**今日验收标准**：能解释 health tracker 的 cooldown（冷却）逻辑和 circuit breaker（熔断器）的关系。

---

## Day 7：整合 + 模拟面试（决战日）

### 上午：整合
- [ ] 打开 `CODE_MAP_大白话版.md`，逐文件过一遍
- [ ] 画 A4 纸时序图：Router→Notetaker→Planner→Executor（按时间顺序的流程图）
- [ ] 确定 3 个 show off（展示/炫技）代码片段（建议：protocol.py frozen dataclass、hybrid_recall.py 三路融合、llm_judge.py 保守策略）

### 下午：模拟面试（必须录音或找人）
- [ ] 5 分钟快速版（不看稿）
- [ ] 10 个灵魂追问，每个回答 1-2 分钟
- [ ] 现场打开代码，指给"面试官"看 3 个关键实现

### 晚上：查漏补缺
- [ ] 复习桌面学习计划里的"错误手册"TOP 15 报错
- [ ] 复习桌面学习计划里的"知识手册"对比表
- [ ] 确认 `README.md` 里的 clone URL 已修正（`MASE-agent-memory.git`）
- [ ] 确认本地修改已 push（推送到远程仓库，如果近期投递）

**今日验收标准**：能不看任何文档，流利讲 5 分钟项目介绍 + 应对 5 个追问。

---

## 如果今天没达标怎么办？

| 情况 | 对策 |
|------|------|
| 源码读不完 | 只看 `CODE_MAP_大白话版.md` 标注的"关键行"，其他跳过 |
| 实验跑不通 | 记录报错，查桌面学习计划的`错误手册.md`，不要卡超过 30 分钟 |
| 话术背不熟 | 优先背 `INTERVIEW_CHEATSHEET_大白话版.md` 的 Q1/Q4/Q7/Q9，其他随缘 |
| 时间不够 | 直接跳到 Day 7 的模拟面试，用速查卡临时突击 |

---

## 7 天结束时的最终自检

- [ ] 能打开 SQLite schema（表结构）并解释表结构
- [ ] 能在 CLI 演示跨轮记忆 + 事实覆盖
- [ ] 能画出 5 节点时序图
- [ ] 能手写 Hybrid Recall 公式 + 解释权重
- [ ] 能解释 84.8% 和 80.2% 的区别
- [ ] 能解释 LLM judge 的保守策略
- [ ] 能解释 Circuit Breaker（熔断器）的三态转换
- [ ] 能现场打开代码指出 3 个关键实现
- [ ] 能流利讲 5 分钟项目介绍

**9 项全勾 = 面试-ready。缺 1-2 项 = 有风险。缺 3 项以上 = 需要延期。**

---

> **Kimi 备注**：这个清单是给你每天打勾用的。建议打印出来或放在副屏，完成一项勾一项，有仪式感。
