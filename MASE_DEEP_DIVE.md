# MASE 核心技术深度解析

> 目标：让你对 MASE 的每一行核心代码都知其所以然，面试时能讲到实现细节。

---

## 1. 整体架构哲学

### 1.1 核心主张：先治理记忆，再喂模型上下文

MASE 的名字是 **Memory-Augmented Smart Entity**。它的核心假设是：

> **Agent 记忆的问题不是"模型记不住"，而是"记忆层没有提供可治理的语义"。**

行业默认做法：向量数据库 + RAG → 把相关文本片段塞进 prompt → 让模型自己提炼。

MASE 反对这个默认做法，理由是：
1. **事实会更新，向量只会堆积** —— 旧事实和新事实同时存在，模型无法判断哪个有效。
2. **黑盒不可审计** —— 向量空间无法打开检查，调试时只能猜。
3. **上下文是治理问题，不是窗口大小问题** —— 塞 256k 的原始文本，不如塞 2k 的治理后事实。

### 1.2 双白盒记忆模型

MASE 把记忆拆成两个对象：

| 对象 | 作用 | 存储层 | 可覆盖性 |
|------|------|--------|----------|
| **Event Log** | 保留原始对话和检索入口 | SQLite + FTS5 | 不可覆盖（审计追踪） |
| **Entity Fact Sheet** | 保存最新结构化事实 | SQLite + Markdown tri-vault | **可覆盖**（新事实覆盖旧事实） |

**关键设计**：Entity Fact Sheet 是**覆盖式写入**。当用户说"预算从 5000 改成 8000"时，Notetaker 会调用 `mase2_upsert_fact` 覆盖 `monthly_food_budget` 的值，而不是追加一条新记录。这从根源上消灭了"冲突事实并存"的问题。

### 1.3 存储三层架构

```
L0: 运行时对象层 — Pydantic v2 dataclass / frozen dataclass
L1: 结构化存储层 — SQLite + FTS5（机器检索）
L2: 人类可审计层 — Markdown tri-vault（sessions / context / state）
```

为什么用 SQLite 而不是 PostgreSQL？
- **单文件特性**：一个用户 = 一个 `.db` 文件，备份、迁移、审计极其简单。
- **零运维**：不需要起服务，Agent 启动即用。
- **可携带**：把 `.db` 和 `.md` 文件拷走，记忆就跟着走。

Trade-off：高并发场景下 SQLite 的写锁会成为瓶颈，这是 MASE admitted 的边界。

### 1.4 5 节点 Runtime 管道

```
User Query
    ↓
Router ——→ 判断是否需要检索记忆
    ↓
Notetaker ——→ 检索/写入记忆（唯一有写权限的节点）
    ↓
Planner ——→ 分解任务（≤4 步，不直接回答）
    ↓
Action/Executor ——→ 加载 Fact Sheet + 生成最终答案
    ↓
User
```

**关键设计**：Notetaker 是唯一有写权限的节点。Planner 和 Executor 不能直接或间接修改记忆，这保证了**写入路径单一化**，避免竞争条件。

---

## 2. 架构核心模块详解

### 2.1 MASESystem（engine.py）— 总控台

`MASESystem` 是整个系统的 Façade。它的职责不是做业务逻辑，而是**生命周期管理**。

**核心机制 1：Lazy Agent 注册**
```python
self._agents: dict[str, Any] = get_registry().build_all(
    self.model_interface, self.config_path
)
```
Agent 注册表模式：新增一种 Agent（比如 math specialist）只需要写一个新模块 + 注册，不需要改 MASESystem。

**核心机制 2：Background GC 线程管理**
```python
self._gc_threads: list[threading.Thread] = []
atexit.register(self._atexit_drain)
```
MASE 在后台会 spawn daemon 线程做垃圾回收（比如清理过期 fact、压缩日志）。`atexit` 注册了一个 drain 函数，确保进程退出前等待这些线程完成（timeout 8 秒）。

**为什么重要？**
- 如果你直接用 `kill -9`，daemon 线程会被操作系统强制回收，可能导致 SQLite 写入中断。
- MASE 的 `atexit_drain` + `join_background_tasks(timeout=8.0)`  graceful shutdown 设计，保证了**崩溃后记忆仍然一致**。

**面试追问**："如果 `kill -9` 发生在 SQLite 事务中间，MASE 怎么保证不损坏数据库？"
- SQLite 本身有 WAL（Write-Ahead Logging）机制，事务原子性由 SQLite 保证。
- MASE 的 `atexit_drain` 是在"正常退出"场景下做优雅关闭；`kill -9` 的场景依赖 SQLite 的崩溃恢复能力。
- 但 MASE 的 benchmark runner 做了 **per-case memory isolation**：每个 case 跑完会清掉记忆，下一个 case 从零开始，所以即使上一个 case 的 DB 坏了，也不会污染下一个。

---

### 2.2 Router（router.py）— 路由决策

Router 的职责只有一个：判断当前 query 是否需要检索记忆。

**双路径设计**：

**路径 A：Keyword Fast-Path（零 LLM 调用）**
```python
MEMORY_TRIGGER_PHRASES = (
    "之前", "上次", "刚才", "刚刚", "早先",
    "记得", "还记得", "提到过", "告诉过", "说过",
    "我们讨论", "我们聊", "我们说",
    "那个", "那条", "那次",
    "我的",
)

def keyword_router_decision(query: str) -> str:
    return "search_memory" if any(p in query for p in MEMORY_TRIGGER_PHRASES) else "direct_answer"
```

**路径 B：LLM Router（RouterAgent.decide）**
当 fast-path 判定为 `search_memory` 时，会进一步调用 LLM 做精细判断，并提取检索关键词（≤3 个核心名词短语）。

**为什么保留 fast-path？**
- 延迟优化：90% 的"闲聊/通用知识"问题不需要 LLM 判断，直接走 `direct_answer`。
- 成本优化：本地 7B 模型虽然便宜，但 token 也是钱。
- 可靠性：如果 LLM 挂了，fast-path 仍然能工作（LangGraph orchestrator 里明确处理了 `error` fallback）。

**LangGraph Orchestrator 里的 wiring**：
```python
def router_node(state: AgentState):
    query = state["user_query"]
    # 先走 fast-path
    if _fast_path_enabled():
        decision = keyword_router_decision(query)
        if decision == "direct_answer":
            return {"router_decision": "direct_answer"}
    # Fast-path 没过，走 LLM
    decision = _get_router_agent().decide(query)
    ...
```

**面试追问**："如果用户问'你觉得那个方案怎么样'，fast-path 会命中'那个'，但实际用户可能是在讨论当前文档里的方案，不是历史记忆。怎么处理？"
- 这是 fast-path 的已知误报（false positive）。
- 解决方案：fast-path 只决定"是否值得花一个 LLM hop 做精细判断"，最终决策权在 LLM Router。
- 即使误触发 `search_memory`，如果检索结果为空，Planner 会输出 "direct answer path"，不会硬编答案。

---

### 2.3 Notetaker（notetaker_agent.py）— 记忆的守门人

Notetaker 是 MASE 最核心的创新点。它是**唯一有写权限的节点**，通过工具调用（Function Calling）操作记忆。

**工具集设计**：
```python
NOTETAKER_TOOLS = [
    mase2_write_interaction,   # 写 Event Log
    mase2_upsert_fact,         # 覆盖/插入 Entity Fact
    mase2_search_memory,       # BM25 检索历史对话
    mase2_get_facts,           # 获取结构化事实
    mase2_correct_and_log,     # 用户纠正记忆时记录
    mase2_supersede_facts,     # 批量覆盖事实
]
```

**Tri-Vault Mirror**：
```python
_TRI_VAULT_BUCKET_BY_TOOL = {
    "mase2_write_interaction": "sessions",
    "mase2_upsert_fact": "context",
    "mase2_correct_and_log": "state",
    "mase2_supersede_facts": "state",
}
```
每次工具调用成功后，写入会**同步镜像**到 Markdown tri-vault：
- `sessions`：原始对话日志
- `context`：事实上下文
- `state`：状态变更（纠正、覆盖）

这实现了"一次写入，三层落地"：SQLite 供机器检索，Markdown 供人类审计。

**面试追问**："为什么不直接让模型生成 SQL 操作数据库？"
- 安全：Function Calling 的 schema 约束了参数类型和必填字段，模型只能按契约操作。
- 可观测：每个操作都有明确的名字和参数，便于日志追踪。
- 可替换：如果将来把 SQLite 换成 PostgreSQL，只需要改工具函数的实现，Notetaker 的 prompt 不需要改。

---

### 2.4 Planner（planner_agent.py）— 任务分解

Planner 的设计极其克制：

```python
PLANNER_SYSTEM = """
你是 MASE 的编排 Planner。你的职责是分配任务，不是回答问题。

硬性规则：
1. 绝对不能直接给出最终答案。
2. 绝对不能引入记忆中不存在的新实体、新数字、新日期、新结论。
3. 只输出执行步骤，描述"先做什么、再做什么、最后验证什么"。
4. 如果已有记忆，步骤必须围绕"检索事实 -> 压缩证据 -> 执行/验证"展开。
5. 如果没有相关记忆，只能写"direct answer path"，不能代替执行器作答。

输出要求：
- 最多 4 行
- 每行一个步骤
- 不要解释，不要举例，不要写最终答案
"""
```

**为什么限制 ≤4 步？**
- 减少 LLM 的"过度思考"：Planner 不是 Chain-of-Thought，它是给 Executor 的"执行提纲"。
- 控制延迟：每多一步就多一次 LLM 调用。
- 降低错误累积：步骤越多，中间出错概率越高。

**Fallback 机制**：
```python
def plan(self, query: str, memory_context: str, mode: str | None = "task_planning") -> str:
    if not self.model_interface:
        if memory_context and "无相关记忆" not in memory_context:
            return "1. 结合查找到的记忆。\n2. 直接回答用户问题。"
        return "直接基于常识回答问题。"
```
如果模型接口不可用（比如本地 Ollama 没启动），Planner 会退回到硬编码的极简计划，而不是崩溃。

**面试追问**："Planner 输出'检索事实 -> 压缩证据 -> 执行'，这个压缩是谁做的？"
- **不是 Planner 做的**。Planner 只输出计划文本。
- 真正的"压缩"发生在 **Fact Sheet 构建阶段**（`fact_sheet.py`）：Notetaker 检索到原始文本后，`build_long_context_fact_sheet` 会提取匹配词周围的窗口（`window_radius`），把长文本压缩成若干证据片段。
- Executor 最终看到的是压缩后的 Fact Sheet，不是原始文档。

---

### 2.5 Executor（executor.py）— 最终回答

Executor 的设计非常简洁：加载 system prompt + memory context + user query，调用 LLM 生成回答。

```python
system_prompt = (
    "You are a helpful, intelligent assistant.\n"
    "You are provided with a user query and relevant memory context...\n"
    "If the memory context does not contain the answer or is empty, "
    "answer to the best of your knowledge, but clarify that you don't have a specific memory..."
)
```

**关键设计：Honesty Prompt**
如果记忆上下文为空，Executor 被明确要求" clarify that you don't have a specific memory"。这防止了模型在检索失败时编造答案（幻觉）。

**面试追问**："如果 Executor 看到的事实互相矛盾，它怎么处理？"
- 理论上，Entity Fact Sheet 不应该有矛盾，因为 Notetaker 的 `upsert_fact` 是覆盖式的。
- 但如果用户在同一个 session 里先说了 A 后说了 B，而 B 还没被 Notetaker 处理，Executor 可能同时看到 A（来自 Event Log 检索）和 B（来自 Fact Sheet）。
- 当前 MASE 的缓解策略是：Fact Sheet 优先于 Event Log。Executor 的 prompt 里 Fact Sheet 放在前面，Event Log 放在后面，模型倾向于信任更结构化的 Fact Sheet。
- 长期方案：给 fact 加 confidence score 和 timestamp，让 Executor 做显式的冲突消解。

---

### 2.6 Protocol（protocol.py）— 消息宪法

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

**三个关键设计**：
1. `frozen=True`：消息不可变。下游节点不能偷偷改 payload，避免调试时"谁改了我的数据"的抓狂。
2. `default_factory=dict`：避免 Python 经典的"可变默认参数"坑。
3. `_utc_now_iso`：时间戳用 UTC ISO8601，不带时区歧义。

**面试追问**："为什么用 dataclass 而不是 Pydantic BaseModel？"
- AgentMessage 是内部协议，不需要 JSON Schema 验证和序列化。
- dataclass 更轻量，frozen dataclass 的 hash 支持更好（可以作为 dict key）。
- 但如果未来需要跨进程序列化（比如 gRPC），可以无痛换成 Pydantic，因为字段定义完全一致。

---

## 3. 记忆与检索系统详解

### 3.1 MemoryService（memory_service.py）— 记忆服务门面

MemoryService 是一个纯静态方法的数据类，它是 **tri-vault API 的 Python 封装层**。

```python
@dataclass
class MemoryService:
    def remember_event(self, thread_id, role, content, scope_filters=None): ...
    def upsert_fact(self, category, key, value, reason=None, ttl_days=None): ...
    def search_memory(self, keywords, limit=5): ...
    def recall_timeline(self, thread_id=None, limit=50): ...
    def correct_memory(self, thread_id, utterance, extra_keywords=None): ...
```

**Scope Filter 设计**：
```python
def _scope(self, scope_filters):
    return {k: v for k, v in dict(scope_filters or {}).items() if v not in (None, "")}
```
所有记忆操作都支持 `scope_filters`，这允许在多租户场景下按 `user_id`、`project_id` 等维度隔离记忆。当前默认是空 scope（单用户）。

---

### 3.2 Fact Sheet 构建（fact_sheet.py）— 上下文压缩的艺术

`build_long_context_fact_sheet` 是 MASE 长上下文性能的核心。

**输入**：用户问题 + 检索结果（raw chunks）
**输出**：压缩后的证据文本（通常几千 token）

**三档配置**（由 mode_selector 根据长度桶自动选择）：

| 场景 | window_radius | max_windows | header 语义 |
|------|---------------|-------------|-------------|
| Long Memory | 420 | 4 | 历史聊天证据，按 relevance 排序 |
| Multi-doc | max(380, bucket-based) | 6 | 多文档证据，注意 cross-check |
| Single long context | 220 | 4 | 单文档证据，按 relevance 排序 |

**关键函数：`extract_focused_window`**
这个函数在原始 chunk 中，围绕匹配到的关键词，提取半径为 `window_radius` 的文本窗口。不是把整个 chunk 塞进去，而是只取关键词附近的上下文。

**面试追问**："window_radius=420 是什么意思？是字符还是 token？"
- 从代码看，这是**字符数**（因为直接对 Python string 做 slice）。
- 420 个汉字 ≈ 210-280 个 token（取决于 tokenizer），所以一个 window 大约几百 token。
- 4 个 windows + header + candidate table，总长度控制在 2000-4000 token 左右。
- 这就是为什么 256k 的文档，模型实际看到的只有 ~16k：原始文档被切成了 chunks，检索只取 top-K chunks，每个 chunk 又被窗口化，最终只剩精华。

---

### 3.3 Hybrid Recall（hybrid_recall.py）— 三路融合

Hybrid Recall 的公式：
```
score = α * dense + β * BM25 + γ * temporal
默认：α=0.5, β=0.3, γ=0.2
```

**三路分别是什么**：
1. **Dense**：向量相似度（来自 SQLite 的 embedding 检索或外部向量库）。
2. **BM25**：关键词匹配分数。MASE 内置了一个 `_InlineBM25` 实现（当 `rank_bm25` 库未安装时的 fallback）。
3. **Temporal**：时间感知加分。检测 query 中的时间词（"昨天"、"上周"、"上个月"），给近期记忆加权。

**Temporal 实现细节**：
```python
_TEMPORAL_CUES_RECENT = ("昨天", "今天", "刚才", "刚刚", "最近", ...)
_TEMPORAL_CUES_WEEK = ("上周", "本周", "这周", "前几天", ...)
_TEMPORAL_CUES_MONTH = ("上个月", "本月", "这个月", "几周前", ...)

def _detect_temporal_window(query):
    for cue in _TEMPORAL_CUES_RECENT:
        if cue in q: return "recent", timedelta(days=2)
    for cue in _TEMPORAL_CUES_WEEK:
        if cue in q: return "week", timedelta(days=7)
    ...
```

不是用 LLM 判断时间，而是用**关键词匹配**。为什么？
- 快：O(n) 字符串匹配，零 LLM 调用。
- 准：中文时间表达相对固定，规则覆盖率高。
- 可控：误匹配不会致命，只是给记忆加了一个微弱的权重偏移。

**归一化策略**：
```python
def _minmax_normalize(values):
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12: return [0.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]
```
每一路单独做 min-max 归一化后再加权，避免某一路的绝对数值范围过大压制其他路。

**面试追问**："如果三路都返回了不同的 top-1 结果，怎么融合？"
- 不是取交集，而是**并集 + 重排**。三路各自产出候选列表，合并后按加权分数重新排序。
- 这样做的好处是不漏召回：只要有一路命中了正确答案，它就有机会被排上来。
- 代价是候选池变大，计算量增加。但 cross-encoder rerank（在 multipass 里）会进一步精排，所以总体可控。

---

### 3.4 Multi-pass Retrieval（multipass_retrieval.py）— 检索增强

Multi-pass 是 MASE 的"重型武器"，默认关闭（`MASE_MULTIPASS=1` 才开启）。

**五阶段管道**：

```
A. Baseline —— 原始 keywords 做单轮检索（锚定结果）
B. Query Rewrite —— 小模型（qwen2.5:1.5b）生成 2-3 个 paraphrase
C. HyDE —— 小模型起草假想答案，提取关键词再检索
D. Cross-Encoder Rerank —— bge-reranker-v2-m3 对合并后的候选精排
E. Safety Net —— 如果 multipass 召回 < baseline 的一半，回退到 baseline
```

**Query Rewrite 缓存**：
```python
@lru_cache(maxsize=512)
def _generate_query_variants_cached(question: str, n: int) -> tuple[str, ...]:
    prompt = f"请为下面的问题生成 {n} 个不同表述但语义等价的改写..."
    ...
```
用 LRU cache 避免对同一个问题反复调用 LLM。这在 benchmark 跑批时特别重要（同一个问题可能被多次检索）。

**HyDE（Hypothetical Document Embedding）**：
```python
prompt = (
    "假设你已经知道答案, 请用 1-2 句话直接陈述对下面问题最可能的答案 "
    "(不需要正确, 只需要包含可能涉及的关键名词与术语):"
)
```
让小模型生成一个"假想的正确答案"，然后从答案中提取关键词做第二轮检索。这能有效解决"用户问题太短、关键词不足"的问题。

**Safety Net**：
```python
# 伪代码逻辑
if len(multipass_results) < len(baseline_results) / 2:
    return baseline_results
```
Multi-pass 的每个阶段都可能失败（模型挂了、reranker 加载失败）。Safety Net 保证：**multi-pass 永远不会比 baseline 更差**。

**面试追问**："HyDE 会不会引入幻觉关键词，反而检索到无关内容？"
- 会，这是 HyDE 的已知风险。小模型生成的假想答案可能包含幻觉实体。
- MASE 的缓解策略：
  1. HyDE 只提取**名词和术语**（正则过滤），不保留完整句子；
  2. 提取结果和原始 query 的检索结果**合并去重**，不是替代；
  3. 最终有 cross-encoder rerank 做精排，幻觉内容的 rerank 分数通常较低。

---

### 3.5 Mode Selector（mode_selector.py）— 智能分桶

Mode Selector 是 MASE 的"自动档"：根据任务类型和输入长度，自动选择最佳策略。

**长度桶映射**：
```python
def long_context_search_limit(default=10):
    return {
        "16k": 12, "32k": 15, "64k": 20, "128k": 30, "256k": 30,
    }.get(bucket, default)

def long_context_window_radius(default=220):
    return {
        "16k": 240, "32k": 280, "64k": 320, "128k": 380, "256k": 420,
    }.get(bucket, default)
```

规律：长度越大，`search_limit` 越高（需要检索更多 chunks 来覆盖全文），`window_radius` 越大（每个 chunk 保留更多上下文）。

**Task Family 检测**：
- `MASE_TASK_TYPE=long_context_qa` → LV-Eval 类任务
- `MASE_TASK_TYPE=long_memory` → LongMemEval 类任务
- 普通对话 → 不走 multipass，节省资源

**面试追问**："这些数字（12, 15, 20, 30）是怎么调出来的？"
- 这是 empirically tuned：先在 32k 上手动试几个值，看 recall 和 latency 的平衡点，然后按长度比例外推到其他桶。
- 不是数学推导出来的，是实验调参。承认这一点不丢人，因为所有系统的超参都是这样来的。
- 但 MASE 的优势是：这些超参被**文档化**了，而且通过 env var 可调，方便 ablation。

---

### 3.6 Reasoning Engine（reasoning_engine.py）— 推理工作区

Reasoning Engine 构建一个 `ReasoningWorkspace`，它是一个 frozen dataclass：

```python
@dataclass(frozen=True)
class ReasoningWorkspace:
    operation: str           # lookup / update / difference / duration / money / count / chronology / disambiguation
    focus_entities: list[str]
    target_unit: str
    sub_tasks: list[str]
    verification_focus: list[str]
    deterministic_answer: str
    evidence_confidence: str
    verifier_action: str
    followup_needed: bool
```

**Operation Classification**：
```python
def _classify_operation(question: str) -> str:
    if "最新" in lowered or "current" in lowered: return "update"
    if "difference" in lowered or "compare" in lowered: return "difference"
    if "how long" in lowered or "duration" in lowered: return "duration"
    if "how much" in lowered or "spent" in lowered: return "money"
    if "how many" in lowered or "count" in lowered: return "count"
    if "latest" in lowered or "earliest" in lowered: return "chronology"
    if "who" in lowered or "which" in lowered: return "disambiguation"
    return "lookup"
```

这个分类器的输出会影响：
1. **Fact Sheet 的构建策略**：比如 `chronology` 类问题需要保留时间戳；`disambiguation` 类问题需要 candidate table。
2. **Verifier 的触发策略**：`update` 类问题（用户改变了偏好）需要更强的验证。

**面试追问**："这个分类器是规则-based 的，为什么不直接用 LLM 做 zero-shot 分类？"
- 规则分类器零延迟、零成本、可解释。
- LLM 分类虽然更灵活，但会引入不确定性（同一个问题两次分类结果可能不同），而 ReasoningWorkspace 是 frozen 的，需要确定性。
- 当规则分类器不确定时（默认返回 "lookup"），系统会走最保守的路径，不会做错事。

---

## 4. Eval 体系详解

### 4.1 Benchmark Runner（runner.py）— 评测发动机

runner.py 是 1000+ 行的大模块，核心职责：

**1. Per-Case Memory Isolation**
每个 benchmark case 跑完后，记忆被清空，下一个 case 从零开始。这防止了 case A 的记忆泄漏到 case B。

**2. Config Profile Resolution**
```python
def _load_config_profiles():
    registry_path = BASE_DIR / "config.profiles.json"
    ...
```
支持通过 `config.profiles.json` 定义不同的运行配置（本地模型 vs 云模型 vs 不同长度桶）。

**3. Call Log Aggregation**
```python
def _aggregate_call_log(call_log):
    by_agent = {}
    for item in call_log:
        agent_type = item.get("agent_type")
        by_agent[agent_type]["call_count"] += 1
        by_agent[agent_type]["elapsed_seconds"] += ...
        by_agent[agent_type]["usage_totals"] += ...
```
记录每个 Agent 的调用次数、耗时、token 用量。这是做**成本分析**和**延迟分析**的基础。

**4. Dataset Fingerprint**
```python
# 生成 sample_ids 和 payload 的 SHA-256
sample_ids_sha256 = hashlib.sha256(",".join(sorted(sample_ids)).encode()).hexdigest()
```
确保结果可复现：如果你声称跑的是 NoLiMa 32k，runner 会记录实际用到的 sample IDs 的哈希，防止"用了不同的 subset 却说跑的是同一个 benchmark"。

---

### 4.2 LLM-as-Judge（llm_judge.py）— 保守的评委

```python
_JUDGE_SYSTEM = (
    "You are an expert evaluator... "
    "Treat semantically equivalent phrasings, paraphrases, and answers that include "
    "the reference content (even with extra context) as correct."
)
```

**核心设计：保守策略（只升级，不降级）**

在 `score_sample` 中（`benchmarks/scoring.py`）：
1. 先跑 **substring matching**（官方标准）
2. 如果 substring 失败，且 `MASE_USE_LLM_JUDGE=1`，调用 LLM judge
3. Judge 认为正确 → 升级为 pass
4. Judge 认为错误 → **不降级**，仍然保持 fail

```python
# scoring.py 中的逻辑（推测，基于 llm_judge.py 的描述）
if substring_match:
    score = 1.0
else:
    if use_llm_judge:
        judge_result = judge_answer(question, ground_truth, answer)
        if judge_result is True:
            score = 1.0  # 升级
        else:
            score = 0.0  # 维持 fail，不是 downgrade
    else:
        score = 0.0
```

**为什么这样设计？**
- Substring matching 会**系统性漏判**：比如答案是"苹果"，模型回答"我推荐苹果（iPhone）"，substring 匹配失败，但语义正确。
- LLM judge 会**系统性误判**：评委模型有长度偏见、格式偏见。
- 保守策略平衡了两者：只修复 substring 的漏判，不引入评委的误判。

**Judge Cache**：
```python
_JUDGE_CACHE: dict[str, bool] = {}
```
同一个 (question, ground_truth, answer) 组合只评判一次，避免重复调用云模型 API。

---

### 4.3 Anti-Overfit Policy — 工程纪律

这是 MASE 最反常识、最加分的设计。它不是代码，是**文档化的工程纪律**。

**四大禁令**：
1. **禁止 qid-based routing**：不能根据题目 ID 决定走哪条策略。
2. **禁止 cherry-picked reruns**：不能把多次运行中最好的结果当作 headline。
3. **禁止 failed-slice retry 混入 public claim**：对失败的子集重跑后，不能把它和第一次跑的成功子集合并报告。
4. **禁止 tuning on holdout**：不能用测试集调参，然后声称测试集是干净的。

**Regression Guards**：
```python
# tests/test_overfit_guards.py
# 检查 benchmark runner 里没有 qid-based routing
# 检查 publishable LongMemEval 脚本设置了 MASE_LME_ROUTE_BY_QID=0
# 检查 claim manifest 引用了 tracked evidence
```

这些测试在 CI 里运行，如果有人不小心提交了违规代码，CI 会 fail。

**面试追问**："这些规则是不是太严格了？很多论文都用过 ablation 和 retry。"
- 学术论文的 benchmark 和工程产品的 benchmark 目的不同。
- 论文追求"展示潜力"，产品追求"诚实评估"。
- MASE 的 anti-overfit policy 不是为了发论文，是为了让团队**敢改代码**。如果数字是 cherry-picked 的，你改了一行代码，发现数字掉了 5%，你不敢合并；但如果数字是 honest 的，掉了 5% 就是真掉了，你可以回退或修复。
- 这套纪律让 MASE 的迭代速度更快，因为**不怕回退**。

---

## 5. 工程基建详解

### 5.1 Event Bus（event_bus.py）— 去耦合的神经系统

```python
@dataclass(frozen=True)
class Event:
    topic: str           # e.g. "mase.route.decided"
    payload: dict
    trace_id: str        # 跨节点关联
    timestamp: float
```

**设计要点**：
- **Pub/Sub 模式**：任何模块可以订阅任何 topic，不需要 engine 知道订阅者存在。
- **Prefix Matching**：订阅 `"mase.model"` 可以收到所有 model 相关事件。
- **Fire-and-Forget**：subscriber 异常被捕获，不会 crash engine。
- **Sync Only**：故意不做 async，因为 benchmark 需要确定性顺序。

**面试追问**："Event Bus 是 in-memory 的，如果进程崩溃了，这些事件是不是全丢了？"
- 是的，Event Bus 是运行时诊断工具，不是持久化日志。
- 持久化日志由 `structured_log.py` 和 SQLite 负责。
- Event Bus 的作用是**实时观测**：比如你可以在 CLI 里订阅 `"mase.executor.done"`，每次回答生成后打印一条消息。

---

### 5.2 Model Interface（model_interface.py）— 模型统一接口

ModelInterface 是 MASE 的"模型驱动层"，支持多后端：
- **Local**：Ollama、llama.cpp
- **Cloud**：Moonshot、OpenAI、DeepSeek、Zhipu/GLM

**Cloud Model Policy**：
```python
def _enforce_cloud_model_policy(provider, agent_type, mode, model_name):
    if provider in {"ollama", "llama_cpp"} or cloud_models_allowed():
        return
    raise RuntimeError("Cloud model call blocked by policy...")
```

默认**禁止**调用云模型，必须显式设置 `MASE_ALLOW_CLOUD_MODELS=1`。这是一个**隐私/成本保护**设计：用户默认使用本地模型，不会不小心把数据发到云端。

**Config Resolution 链**：
```
1. 传入的 config_path 参数
2. MASE_CONFIG_PATH 环境变量
3. ./config.json（当前目录）
4. 项目根目录 config.json
5. ~/.mase/config.json
```
这让 MASE 在不同部署场景下都能找到配置。

---

### 5.3 Circuit Breaker（circuit_breaker.py）— 熔断器

基于 `health_tracker` 的轻量封装：
- `closed`：正常调用
- `open`：连续失败 N 次后，快速失败，不再浪费请求
- `half_open`：冷却时间过后，放一次请求试探恢复

**为什么不用 pybreaker？**
因为项目已经有 `health_tracker` 的 cooldown 逻辑，再加 pybreaker 会引入第二个状态源。这个 wrapper 只有 50 行代码，复用了现有的 health state。

---

### 5.4 Adaptive Verify（adaptive_verify.py）— 自适应验证深度

根据检索信号的质量，动态选择验证策略：

```python
Decision = Literal["skip", "single", "dual"]

HARD_QTYPES = frozenset({"multi-session", "temporal-reasoning"})
```

**决策逻辑**：
1. **Skip**：top-1 retrieval score > 0.85，且 top-1 和 top-2 的差距 > 0.2（dominant）。直接回答，不验证。
2. **Single**：中等置信度，走单 verifier（kimi-k2.5）。
3. **Dual**：低置信度（score < 0.5）或 hard qtype（multi-session / temporal-reasoning）。走双 verifier 投票。

**面试追问**："dominance_gap=0.2 是什么意思？"
- 即使 top-1 score 很高（比如 0.9），如果 top-2 也有 0.85（gap=0.05），说明候选答案很接近，系统不能确定哪个是对的。
- 这时即使 score > skip_threshold，也不会 skip，而是走 single verifier。
- 这是**避免过度自信**的设计。

---

## 6. 面试灵魂追问 & 代码级回答

以下问题按出现频率排序，每个问题都附带了**根因分析**和**改进方向**。

### Q1：SQLite 在 10 万条事实时的检索延迟是多少？瓶颈在哪？

**当前状态**：
- MASE 用 SQLite + FTS5 做全文检索。FTS5 是倒排索引，检索复杂度接近 O(1)（查索引表）。
- 但 `hybrid_recall` 需要在 Python 里做三路融合和重排，这部分是 O(n log n)。
- 当前没有显式 benchmark 过延迟，但按 SQLite 性能，10 万条文档的 FTS5 查询通常在 **10-50ms**。

**瓶颈**：
1. 如果 `BM25` 用 `_InlineBM25`（纯 Python 实现），对大数据集会慢。
2. `multipass_retrieval` 里有 cross-encoder rerank，这个模型在 CPU 上跑 30 个候选需要 **几百毫秒到几秒**。

**优化方向**：
- SQLite → PostgreSQL + pg_trgm/pgvector（保留 FTS5 语义，但提升并发）。
- cross-encoder 改为 GPU 推理或换轻量级模型。
- 给 fact 加**时间分区索引**（按月份分表），减少扫描范围。

---

### Q2：LangGraph 的 checkpoint 机制在崩溃恢复时有什么坑？

**MASE 的用法**：
MASE 用 LangGraph 做 orchestration，但**没有依赖 LangGraph 的 checkpoint 做状态持久化**。MASE 的状态持久化是自己做的（SQLite + atexit drain）。

**为什么不用 LangGraph checkpoint？**
- LangGraph 的 checkpoint 默认是 in-memory 或需要额外配置 Redis/Postgres。
- MASE 的记忆层（SQLite）已经是持久化的，LangGraph 的状态只是"当前运行时的中间变量"，不需要单独 checkpoint。
- 如果进程崩溃，LangGraph 的状态丢失没关系，因为用户的记忆已经在 SQLite 里了。重启后从 SQLite 重新加载即可。

**坑**：
- LangGraph 的 `StateGraph` 如果配置了 checkpoint，会在每个 node 结束后写状态。这会增加延迟。
- MASE 的 `langgraph_orchestrator.py` 没有开 checkpoint（从代码看没有 `checkpointer` 参数），所以不存在这个问题。

---

### Q3：7B 模型的收益会不会被 70B 模型稀释？

**核心观点**：MASE 的收益来自**上下文压缩和事实提纯**，不是来自模型能力。

**分析**：
- 70B 模型的裸跑 baseline 会显著高于 7B（可能在 LV-Eval 256k 上从 4.84% 提升到 30-40%）。
- MASE + 70B 的提升空间会变小（因为 baseline 已经很高了），但**绝对值仍然更高**。
- 类比：7B 裸跑 4.84% → MASE 88.71%（+84pp）；70B 裸跑 35% → MASE + 70B 可能 92%（+57pp）。增量变小，但绝对值更高。

**更重要的问题**：MASE 让 7B 模型**可用**了。在没有 MASE 时，7B 模型在长上下文场景下几乎不能用（4.84%）；有了 MASE，它可以部署在消费级硬件上服务真实用户。这是成本上的质变。

---

### Q4：两个用户同时更新同一个 Entity Fact Sheet，会不会 lost update？

**当前状态**：MASE 是单进程架构，SQLite 的默认隔离级别是 **SERIALIZABLE**（实际上 SQLite 在 WAL 模式下是 **SNAPSHOT ISOLATION**，写操作是串行的）。

**在单进程场景下**：
- 没有并发写，不会 lost update。

**在多进程/多线程场景下**：
- SQLite 的写锁是**数据库级**的，不是表级或行级。如果一个进程在写，其他进程的写会被阻塞。
- 这会导致延迟飙升，但**不会 lost update**（因为 SQLite 的 ACID 保证了原子性）。

**如果要支持高并发**：
- SQLite → PostgreSQL，利用行级锁和 MVCC。
- 或者把 Entity Fact Sheet 按 `user_id` 分片到不同的 SQLite 文件（每个用户一个 DB），消除写竞争。

---

### Q5：LongMemEval 里做错的 case，共同模式是什么？

**你需要亲自做这件事**：打开 `docs/benchmark_claims/evidence/longmemeval_iter2_dual_lane_summary.json`，分析错误的 case。

**预期的失败模式**（基于架构推断）：
1. **Temporal Reasoning 失败**：用户问"上周三我说的预算"，系统没有精确到"上周三"，而是返回了最新的预算。
2. **Multi-session Synthesis 失败**：用户在 Session 1 说了偏好 A，Session 3 说了偏好 B，问题是"用户更喜欢 A 还是 B"，系统只检索到了最新的 B。
3. **Synonym Mismatch**：用户用"经费"问，但记忆里的 key 是"预算"，BM25 没匹配到。
4. **Conflicting Facts**：用户说"不吃辣"（临时），但 Fact Sheet 覆盖了永久偏好，导致后续问题回答错误。

**改进方向**：
- 给 fact 加 `valid_from` / `valid_until` / `confidence` 字段。
- 做多跳检索（session A → session B → 关联事实）。
- 接入 learned sparse retrieval（SPLADE）解决同义词问题。

---

## 7. 你需要立刻做的功课

1. **手动跑一遍 benchmark**，打开 result JSON，亲自看 5 个做错的 case，理解为什么错。
2. **读一遍 `src/mase/fact_sheet_long_memory.py`**，理解 LongMemEval 的 fact sheet 构建和普通 QA 有什么不同。
3. **确认 `mase_tools/memory/` 的 tri-vault 实现**：理解 SQLite schema 和 Markdown 是怎么同步的。
4. **做一次 `kill -9` 实验**：在 MASE CLI 运行时 `kill -9` 进程，然后重启，验证记忆是否完整恢复。
5. **尝试加一个 Agent**：比如加一个 `math_planner`，注册到 agent_registry，理解扩展机制。

做完这 5 件事，你对 MASE 的理解就超过 99% 的"读过代码"的人了。

---

*文档结束。如果某个模块你想再深挖，告诉我具体文件和行号范围。*
