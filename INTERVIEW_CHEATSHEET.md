# MASE 面试速查卡（10 道灵魂追问 + 代码级回答）

> ⚠️ **Kimi 生成文件**：本文件由 Kimi 根据源码逐行分析后撰写，可直接背诵。
> 🎯 用途：面试前 3 天反复自测，确保每个问题都能答到代码级别。

---

## Q1：为什么不用向量数据库？

**回答结构**：三宗罪 + MASE 解法 + 代码佐证

> "向量数据库作为 Agent 记忆的默认底座有三个结构性问题：
> 1. **事实会过时，向量只会堆积**。用户说'预算 5000'后又说'改成 8000'，向量库里两条同时存在，模型无法判断哪个有效。
> 2. **黑盒不可调试**。召回错了你只能调 embedding 模型或 top-k，打不开向量空间看看到底发生了什么。
> 3. **长上下文是治理问题，不是窗口问题**。塞 256k 原始文本，不如塞 2k 治理后的最小必要事实。
>
> MASE 的做法是双白盒：
> - **L1 SQLite + FTS5**：结构化事件流水 + 可读的 BM25 召回，能直接 `SELECT *` 检查。
> - **L2 Markdown tri-vault**：每次写入同步镜像到 JSON 文件，能 `git diff` 看记忆怎么变的。
> - **Entity Fact Sheet**：新事实通过 `mase2_upsert_fact` **覆盖**旧事实，从源头消灭冲突。
>
> 代码上，`mase_tools/memory/api.py` 第 40-58 行的 `mase2_upsert_fact` 就是覆盖入口，底层 SQL 是 `INSERT OR REPLACE` 语义，不是 append-only。"

**面试官可能追问**："SQLite 的 BM25 能比得上向量语义检索吗？"

> "在同义词/近义表达上确实不如向量，这是 MASE admitted 的边界。但 MASE 预留了 hybrid 通道：`src/mase/hybrid_recall.py` 第 8-12 行，`score = α*dense + β*bm25 + γ*temporal`，dense 那路可以接向量。当前默认 α=0.5, β=0.3, γ=0.2，说明 BM25 只是三路之一，不是全部。"

---

## Q2：冲突事实怎么处理？

**回答结构**：覆盖语义 + 纠正检测 + 审计链

> "MASE 处理冲突的核心是**显式覆盖**，不是隐式堆积。
>
> 第一层是 `upsert`：Notetaker 调用 `mase2_upsert_fact(category, key, value)` 时，底层 SQL 会用 `INSERT OR REPLACE` 或等价逻辑，保证同一个 `category.key` 只有一行最新值。
>
> 第二层是 `supersede`：用户说'我之前说错了'时，`correction_detector.py` 第 14-33 行的正则触发词会命中，自动把旧流水账标记为 `superseded`，新值写入。`mase_tools/memory/api.py` 第 81-91 行的 `mase2_supersede_facts` 就是做这个的。
>
> 第三层是审计：`mase2_get_fact_history` 能查一条事实的完整演化链，相当于给每条事实加了 Git 提交记录。Mem0 没有这个功能，但 MASE 有。"

**面试官可能追问**："如果用户在同一个 session 里先说了 A 后说了 B，但 B 还没被 Notetaker 处理，Executor 同时看到 A 和 B 怎么办？"

> "当前缓解策略是**Fact Sheet 优先于 Event Log**。Executor 的 prompt 里 Fact Sheet 放在前面，Event Log 放在后面，模型倾向于信任更结构化的 Fact Sheet。长期方案是给 fact 加 `confidence_score` 和 `valid_until` 字段，让 Executor 做显式冲突消解。"

---

## Q3：Router 为什么保留 keyword fast-path？

**回答结构**：延迟 + 成本 + 可靠性

> "Router 有两条路径：
> 1. **Keyword fast-path**：`src/mase/router.py` 第 43-49 行定义了 `MEMORY_TRIGGER_PHRASES`，包含'之前'、'上次'、'那个'等 15 个中文触发词。`keyword_router_decision` 做 O(n) 字符串匹配，零 LLM 调用。
> 2. **LLM Router**：fast-path 判定为 `search_memory` 后，再调用 LLM 精细判断并提取关键词。
>
> 保留 fast-path 的三个原因：
> - **延迟**：90% 的闲聊/通用知识问题不需要花一个 LLM hop 判断。
> - **成本**：本地 7B 模型虽然便宜，但 token 也是钱。
> - **可靠性**：如果 LLM 挂了，fast-path 仍然能工作。`langgraph_orchestrator.py` 第 110-120 行明确处理了 `error` fallback。
>
> 误报（比如'那个方案'触发 search_memory 但用户指当前文档）会被 LLM Router 二次过滤，不会硬编答案。"

---

## Q4：256k 长上下文 88% 准确率怎么做到的？

**回答结构**：三板斧 + 数据 + 代码

> "核心不是模型参数量，是**上下文治理三板斧**：
>
> **1. Hybrid Recall 混合召回**
> `src/mase/hybrid_recall.py` 第 8-12 行：
> ```python
> score = α * dense + β * bm25 + γ * temporal
> # 默认 α=0.5, β=0.3, γ=0.2
> ```
> 三路各自 min-max 归一化后再加权，避免某一路压制其他路。temporal 路检测'昨天/上周/上个月'，给近期记忆动态加权。
>
> **2. Fact Sheet 提纯**
> `src/mase/fact_sheet.py` 第 19-85 行的 `build_long_context_fact_sheet`：
> - 不是塞原始 256k 文本，而是检索 top-K chunks
> - 每个 chunk 用 `extract_focused_window` 取关键词周围的窗口（`window_radius` 字符）
> - 256k 场景下 `window_radius=420`，`max_windows_per_chunk=4`
> - 最终 Executor 看到的只有几千到一万字符，但覆盖了全部关键证据
>
> **3. Adaptive Verify 分档校验**
> `src/mase/adaptive_verify.py`：
> - top-1 score > 0.85 且 gap > 0.2 → **skip**，直接回答
> - 中等置信 → **single** verifier（kimi-k2.5）
> - score < 0.5 或 hard qtype → **dual** verifier 投票
>
> 结果：qwen2.5:7b 裸跑 LV-Eval 256k 只有 **4.84%**，上 MASE 后 **88.71%**。"

**面试官可能追问**："window_radius=420 是字符还是 token？"

> "是字符数，直接对 Python string 做 slice。420 个汉字约 200-300 个 token。4 个 windows + header + candidate table，总长度控制在 2000-4000 token 左右。模型从未看过完整 256k，但拿到了治理后的最小必要事实集。"

---

## Q5：HyDE 会不会引入幻觉关键词？

**回答结构**：承认风险 + 三层缓解

> "会，这是 HyDE 的已知风险。小模型生成的假想答案可能包含幻觉实体。
>
> MASE 有三层缓解：
> 1. **只提取名词和术语**：`multipass_retrieval.py` 第 143-147 行，用正则 `r'[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}'` 过滤，不保留完整句子。
> 2. **合并去重**：HyDE 结果和原始 query 的检索结果合并，不是替代。原始 query 作为锚定，HyDE 只是补充。
> 3. **Cross-encoder 精排**：`bge-reranker-v2-m3` 对合并候选重新打分，幻觉内容的 rerank 分数通常较低，会被过滤。
>
> 最后还有 **safety net**：如果 multipass 召回 < baseline 一半，直接回退到 baseline 结果。"

---

## Q6：模型挂了系统还能跑吗？

**回答结构**：health tracker + circuit breaker + fallback

> "三层防护：
>
> **1. CandidateHealthTracker**
> `src/mase/health_tracker.py` 第 95-121 行：
> - 记录每个 provider/model 的成功率和 EWMA 延迟
> - `_EWMA_ALPHA = 0.3`，新样本占 30% 权重，既响应快又不过度抖动
> - 连续失败 3 次（`_DEFAULT_COOLDOWN_FAILURES`）进 30 秒 cooldown
>
> **2. Circuit Breaker**
> `src/mase/circuit_breaker.py`：
> - 包装 health tracker 的 cooldown 逻辑为标准 closed/open/half_open 状态
> - open 状态下快速失败，half_open 时放 1 个探测请求
> - 为什么不用 pybreaker？因为已经有 health tracker，再加一层会引入第二状态源。这个 wrapper 只有 50 行。
>
> **3. Fallback**
> - `planner_agent.py` 第 26-30 行：如果 `model_interface` 为 None，回退到硬编码极简计划
> - `router.py` 第 52-57 行：LLM 挂了走 keyword fast-path
> - `executor.py` 第 38-40 行：调用异常时返回友好错误提示，不抛栈"

---

## Q7：84.8% 是必然还是偶然？

**回答结构**：不是偶然 + 不是默认必然 + 工程因果

> "**不是偶然撞大运**，因为提升路径对应明确失败模式：
> - LongMemEval 失败主要集中在 temporal-reasoning、multi-session synthesis、knowledge-update
> - 这些是'证据召回到了，但推理/表述没过'的样本
> - iter4 用 Plan A 二号意见检索：kimi-k2.5 retry + grounded long-memory prompt + 零回退合并器
> - 让更强的 verifier 对困难样本做复核，只采用能提升失败样本的二号意见，避免把原本正确的答案改坏
>
> **但也不是默认必然**，因为 iter4 用了 failed-slice retry 和 post-hoc combined lane，比首跑系统更接近诊断上限实验。
>
> 我的表述是：**84.8% 是真实达到过的里程碑，代表架构上限；80.2% LLM-judge / 61.0% substring 是更保守的公开稳态 headline**。"

---

## Q8：SQLite 10 万条事实时检索延迟多少？瓶颈在哪？

**回答结构**：估计值 + 瓶颈分析 + 优化方向

> "MASE 用 SQLite + FTS5 做全文检索。FTS5 是倒排索引，查询复杂度接近 O(1)，10 万条文档的检索通常在 **10-50ms**。
>
> 但瓶颈不在 SQLite：
> 1. **Hybrid Recall 的 Python 层融合**：三路结果合并、min-max 归一化、重排，是 O(n log n)。
> 2. **Cross-encoder rerank**：`bge-reranker-v2-m3` 在 CPU 上跑 30 个候选需要几百毫秒到几秒。
> 3. **Inline BM25 fallback**：如果 `rank_bm25` 未安装，走纯 Python 实现的 `_InlineBM25`，大数据集会慢。
>
> 优化方向：
> - SQLite → PostgreSQL + pgvector/pg_trgm，提升并发
> - cross-encoder 改 GPU 推理或换轻量级模型
> - 按时间分区索引，减少扫描范围"

---

## Q9：你怎么保证没刷榜？

**回答结构**：双口径 + 四大禁令 + CI 拦截

> "MASE 的 benchmark hygiene 有四层：
>
> **1. 双口径**
> - 最高里程碑 **84.8% LLM-judge(424/500)** 明确标注为 iter4 combined/retry diagnostic
> - 公开稳态 headline 用 **61.0% substring / 80.2% LLM-judge**
> - 不拿诊断结果冒充默认首跑能力
>
> **2. 四大禁令**（`docs/BENCHMARK_ANTI_OVERFIT.md`）
> - 禁止 qid-based routing：不能根据题目 ID 决定策略
> - 禁止 cherry-picked reruns：不能把多次运行中最好的结果当 headline
> - 禁止 failed-slice retry 混入 public claim
> - 禁止 tuning on holdout
>
> **3. Regression Guards**
> `tests/test_overfit_guards.py` 在 CI 里拦截 qid-based routing。
>
> **4. Evidence Provenance**
> 每个 public claim 在 `docs/benchmark_claims/` 下有 manifest，声明数据来源、样本数、SHA-256 fingerprint、anti-overfit 协议版本。"

---

## Q10：如果 Kimi 要接入 MASE，你优先改哪？

**回答结构**：服务端改造 + 记忆治理层建议

> "我会优先做 **async server-grade runtime**：
> 1. **SQLite → PostgreSQL + 按 user_id 分片**：消除单文件写锁瓶颈，支撑并发用户
> 2. **Event bus → Redis Stream / Kafka**：支持分布式事件消费
> 3. **加分布式 session 和无状态化**：MASESystem 实例不保存用户状态，状态全在 DB
>
> 但核心存储抽象（Event Log + Fact Sheet）不需要改，它天然适合按用户分片。
>
> 另外我建议在 Kimi 的 Agent 里引入 MASE 的两个机制：
> 1. **Entity Fact Sheet 主动压缩**：当前多轮对话记忆是上下文拼接，噪声会累积。引入显式的 fact 覆盖和冲突消解。
> 2. **Adaptive Verification**：工具调用链较长时（查天气→查路线→订餐厅），中间错误会级联放大。加轻量级 verifier，根据 confidence 决定是否需要二次确认。"

---

## 背诵建议

| 天数 | 背诵内容 |
|------|---------|
| Day 5 晚上 | Q1（向量库）、Q2（冲突）、Q3（Router） |
| Day 6 晚上 | Q4（88%）、Q5（HyDE）、Q6（熔断） |
| Day 7 早上 | Q7（84.8%）、Q8（延迟）、Q9（反刷榜）、Q10（Kimi 接入） |

**背诵方法**：不看稿，对着镜子或录音，每个问题回答 1-2 分钟。卡壳的地方标记，回去看对应源码行号。

---

> **Kimi 备注**：这 10 道题覆盖了月之暗面 Agent Engineer 面试 80% 的高频追问。如果你能把每道题都答到"能指出行号"的级别，面试官会把你当成同级别的工程师，而不是候选人。
