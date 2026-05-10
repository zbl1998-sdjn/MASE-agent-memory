# MASE 7 天冲刺每日打卡清单

> ⚠️ **Kimi 生成文件**：配合 `7DAY_SPRINT_PLAN.md` 使用，每天完成一项勾一项。

---

## Day 1：双白盒理念 + 存储层

### 上午：读代码
- [ ] 读完 `README.md` 前 70 行，记住三个 benchmark 数字
- [ ] 读完 `docs/ARCHITECTURE_BOUNDARIES.md`
- [ ] 读完 `mase_tools/memory/db_core.py` 前 200 行
- [ ] 在 `db_core.py` 里找到 `CREATE TABLE` 语句，确认 events / entity_state 表结构

### 下午：跑实验
- [ ] `pip install -e ".[dev]"` 成功
- [ ] `python mase_cli.py` 跑起来
- [ ] 输入："我叫张三，预算 5000" → 确认记住
- [ ] 同一对话再问："我预算多少？" → 确认跨轮记忆
- [ ] 用 `sqlite3` 或 DB Browser 打开 `memory/index.db`，执行 `.schema`

### 晚上：背话术
- [ ] 能不看稿说出"为什么不用向量数据库"（2 分钟版本）
- [ ] 能不看稿说出"怎么保证没刷榜"（2 分钟版本）

**今日验收标准**：能打开 SQLite schema 并指出 entity_state 表的主键和覆盖语义。

---

## Day 2：Entity Fact Sheet + 冲突治理

### 上午：读代码
- [ ] 读完 `mase_tools/memory/api.py` 第 40-128 行
- [ ] 读完 `mase_tools/memory/correction_detector.py` 全文
- [ ] 读完 `src/mase/fact_sheet.py` 全文

### 下午：跑实验
- [ ] CLI 说："我喜欢川菜" → 确认写入
- [ ] CLI 说："不对，我说错了，我喜欢粤菜" → 观察纠正检测
- [ ] 查 SQLite：`SELECT * FROM entity_state WHERE key LIKE '%口味%';`
- [ ] 确认旧值被覆盖，不是追加
- [ ] 找到 `db_core.py` 里 `upsert_entity_fact` 的 SQL 实现

### 晚上：背话术
- [ ] 能解释 `supersede` 和 `upsert` 的区别
- [ ] 能说出纠正检测的 3 个中文触发词

**今日验收标准**：能在 CLI 演示"事实覆盖"过程，并用 SQL 验证。

---

## Day 3：Router + Notetaker

### 上午：读代码
- [ ] 读完 `src/mase/router.py` 第 43-117 行
- [ ] 读完 `src/mase/notetaker_agent.py` 第 32-120 行
- [ ] 读完 `src/mase/langgraph_orchestrator.py` 第 39-120 行

### 下午：跑实验
- [ ] 输入"你好" → 确认走 direct_answer
- [ ] 输入"我上次说的预算" → 确认走 search_memory
- [ ] 输入"那个方案怎么样" → 观察是否误触发
- [ ] `set MASE_ORCHESTRATOR_FAST=1`，对比速度
- [ ] `set MASE_ORCHESTRATOR_FAST=0`，对比精度

### 晚上：背话术
- [ ] 能解释 keyword fast-path 的三个保留原因（延迟/成本/可靠性）
- [ ] 能说出 `AgentState` 的 7 个键

**今日验收标准**：能解释 Router 的双路径设计，并演示 fast path 的开关效果。

---

## Day 4：Planner + Executor + Fact Sheet 压缩

### 上午：读代码
- [ ] 读完 `src/mase/planner_agent.py` 全文
- [ ] 读完 `src/mase/executor.py` 全文
- [ ] 读完 `src/mase/fact_sheet_long_memory.py` 全文
- [ ] 读完 `src/mase/mode_selector.py` 第 60-80 行

### 下午：跑实验
- [ ] 读 `examples/04_long_doc_qa_256k.py` 逻辑
- [ ] 修改 config.json 长度桶，观察 search_limit 变化
- [ ] 打印 fact_sheet 长度，确认远小于原始文本

### 晚上：背话术
- [ ] 能手写三路融合公式：`score = 0.5*dense + 0.3*BM25 + 0.2*temporal`
- [ ] 能解释 Planner 为什么限制 ≤4 步

**今日验收标准**：能解释 256k→~16k 的压缩路径，并指出 `window_radius` 的数值。

---

## Day 5：Hybrid Recall + Multi-pass

### 上午：读代码
- [ ] 读完 `src/mase/hybrid_recall.py` 第 1-150 行
- [ ] 读完 `src/mase/multipass_retrieval.py` 第 1-50 行
- [ ] 读完 `src/mase/multipass_retrieval.py` 第 86-147 行

### 下午：跑实验
- [ ] `set MASE_HYBRID_RECALL=1`，跑长文档 QA，对比召回
- [ ] `set MASE_MULTIPASS=1`，观察延迟变化
- [ ] `set MASE_HYBRID_RECALL_WEIGHTS=0.7,0.2,0.1`，观察结果变化
- [ ] 记录结论：哪种权重组合最好？

### 晚上：背话术
- [ ] 能解释 HyDE 的作用和风险
- [ ] 能解释 safety net 的逻辑

**今日验收标准**：能调 env 变量做一次小消融实验，并给出结论。

---

## Day 6：Model Interface + 熔断 + Benchmark

### 上午：读代码
- [ ] 读完 `src/mase/model_interface.py` 第 1-120 行
- [ ] 读完 `src/mase/health_tracker.py` 第 1-107 行
- [ ] 读完 `src/mase/circuit_breaker.py` 全文
- [ ] 读完 `benchmarks/llm_judge.py` 全文

### 下午：跑实验
- [ ] `python -m pytest tests/ -q` → 确认 383/383 passing
- [ ] 挑 3 个测试名有趣的 case，读断言逻辑
- [ ] 跑 benchmark smoke 样本，打开 result JSON
- [ ] `set MASE_ALLOW_CLOUD_MODELS=1`，观察 cloud policy

### 晚上：背话术
- [ ] 能解释 EWMA 0.3 的含义
- [ ] 能画熔断状态转换图（closed→open→half_open）
- [ ] 能解释 LLM judge "只升级不降级"的策略

**今日验收标准**：能解释 health tracker 的 cooldown 逻辑和 circuit breaker 的关系。

---

## Day 7：整合 + 模拟面试

### 上午：整合
- [ ] 打开 `CODE_MAP.md`，逐文件过一遍
- [ ] 画 A4 纸时序图：Router→Notetaker→Planner→Executor
- [ ] 确定 3 个 show off 代码片段（建议：protocol frozen、hybrid 公式、judge 保守策略）

### 下午：模拟面试（必须录音或找人）
- [ ] 5 分钟快速版，不看稿
- [ ] 10 个灵魂追问，每个 1-2 分钟
- [ ] 现场打开代码，指给"面试官"看 3 个关键实现

### 晚上：查漏补缺
- [ ] 复习桌面学习计划里的"错误手册"TOP 15
- [ ] 复习桌面学习计划里的"知识手册"对比表
- [ ] 确认 `README.md` clone URL 已修正
- [ ] 确认本地修改已 push（如果近期投递）

**今日验收标准**：能不看任何文档，流利讲 5 分钟项目介绍 + 应对 5 个追问。

---

## 如果今天没达标怎么办？

| 情况 | 对策 |
|------|------|
| 源码读不完 | 只看 `CODE_MAP.md` 标注的"关键行"，其他跳过 |
| 实验跑不通 | 记录报错，查 `错误手册.md`，不要卡超过 30 分钟 |
| 话术背不熟 | 优先背 `INTERVIEW_CHEATSHEET.md` 的 Q1/Q4/Q7/Q9，其他随缘 |
| 时间不够 | 直接跳到 Day 7 的模拟面试，用速查卡临时突击 |

---

## 7 天结束时的最终自检

- [ ] 能打开 SQLite schema 并解释表结构
- [ ] 能在 CLI 演示跨轮记忆 + 事实覆盖
- [ ] 能画出 5 节点时序图
- [ ] 能手写 Hybrid Recall 公式 + 解释权重
- [ ] 能解释 84.8% 和 80.2% 的区别
- [ ] 能解释 LLM judge 的保守策略
- [ ] 能解释 Circuit Breaker 的三态转换
- [ ] 能现场打开代码指出 3 个关键实现
- [ ] 能流利讲 5 分钟项目介绍

**9 项全勾 = 面试-ready。缺 1-2 项 = 有风险。缺 3 项以上 = 需要延期。**

---

> **Kimi 备注**：这个清单是给你每天打勾用的。建议打印出来或放在副屏，完成一项勾一项，有仪式感。
