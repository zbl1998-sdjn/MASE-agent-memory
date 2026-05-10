# MASE 源码地图（大白话版）

> ⚠️ **Kimi 生成文件（审核重写版）**：本文件由 Kimi 逐行阅读源码后整理，所有英文术语都加了中文翻译，标注了每个文件的作用、面试重点、关键行号。
> 🎯 用途：面试时快速定位代码，回答"给我看看 XX 的实现"。

---

## 先搞懂这些英文词（不然读不下去）

| 英文 | 中文意思 | 大白话解释 |
|------|---------|-----------|
| **fallback** | 兜底/回退 | 主方案挂了，备用方案顶上 |
| **schema** | 表结构/结构定义 | 数据库里的表长什么样，有哪些字段 |
| **handler** | 处理函数 | 收到指令后，具体干活的函数 |
| **fast-path** | 快速通道 | 不走复杂流程，直接抄近路 |
| **env** | 环境变量 | 程序外面的开关，改它不用改代码 |
| **ablation** | 消融实验 | 把某个功能关掉，看分数掉多少，证明这功能有用 |
| **chunk** | 文本块 | 把长文章切成一小段一小段 |
| **rerank** | 重排序 | 先粗筛一堆候选，再用更精细的模型重新打分排序 |
| **embedding** | 嵌入向量 | 把文字转成一串数字，让计算机能算"相似度" |
| **tokenizer** | 分词器 | 把句子切成一个个词或字 |
| **WAL** | 预写日志 | SQLite 的防崩机制，先写日志再写数据，崩了能恢复 |
| **CRUD** | 增删改查 | 创建、读取、更新、删除 |
| **payload** | 载荷/数据内容 | 消息里真正携带的数据 |
| **side-effect** | 副作用 | 函数做了不该做的事，比如偷偷改了全局状态 |
| **gated by env** | 由环境变量控制开关 | 默认关，设 env=1 才开 |
| **degrade gracefully** | 优雅降级 | 主功能挂了，系统不崩，只是效果变差 |
| **pub/sub** | 发布订阅 | 一个人广播消息，多个听众各自接收，互相不认识 |
| **fire-and-forget** | 发完就忘 | 发出消息不等回复，不管对方收没收到 |
| **frozen** | 冻结的/不可变的 | 创建后不能修改 |
| **dataclass** | 数据类 | Python 里专门用来存数据的类，自动生成构造函数 |
| **LLM hop** | LLM 调用次数 | 每调用一次大模型，算一个 hop |
| **holdout** | 留出集 | 专门留出来测试的数据，不能用来调参 |
| **distractor** | 干扰项 | benchmark 里故意塞进去的假信息，测试模型会不会被骗 |
| **top-k** | 前 k 个 | 分数最高的前 k 个结果 |
| **O(n)** | 时间复杂度（与 n 成正比） | 数据量翻一倍，耗时也大约翻一倍 |
| **façade** | 门面/外观 | 给复杂系统包一层简单的皮，对外只暴露几个接口 |
| **daemon** | 守护线程 | 后台默默干活的线程，主程序关了它也可能还在跑 |
| **atexit** | 退出时执行 | Python 的钩子，程序正常退出前自动调用你注册的函数 |
| **registry** | 注册表 | 一个字典，把名字和实现类对应起来，方便动态查找 |
| **monkeypatch** | 猴子补丁 | 运行时偷偷替换某个函数的实现，测试时常用 |
| **orphan** | 孤儿进程/孤立 | 父进程死了，子进程还在，被操作系统接管 |
| **corpus** | 语料库 | 一堆文档的集合 |
| **IDF** | 逆文档频率 | 一个词在越少文档中出现，说明它越重要 |
| **TF** | 词频 | 一个词在文档中出现的次数 |
| **min-max normalize** | 最小最大归一化 | 把一组数压到 0-1 之间，方便比较 |
| **z-score** | Z分数标准化 | 另一种归一化，减去平均值再除以标准差 |
| **EWMA** | 指数加权移动平均 | 越新的数据权重越高，旧数据权重指数衰减 |
| **cooldown** | 冷却时间 | 失败后暂停一段时间，不再尝试，防止把对方打挂 |
| **half-open** | 半开状态 | 熔断器里的一种状态：放少量请求试探对方是否恢复 |
| **verifier** | 校验器/验证模型 | 另一个模型，用来检查主模型的答案对不对 |
| **ground truth** | 标准答案/真实值 | 人工标注的正确答案，用来评判模型 |
| **fingerprint** | 指纹 | 数据的唯一标识，比如 SHA-256 哈希，改了内容指纹就变 |
| **manifest** | 清单/声明 | 一份文件，声明某件东西的来源、版本、验证方式 |
| **tri-vault** | 三仓 | 三个文件夹：context（上下文）、sessions（会话）、state（状态） |
| **halo** | 光环/晕轮 | 在这里指：除了直接命中的行，还要带一点周围的上下文 |

---

## 一、架构核心（面试最高频）

### `src/mase/engine.py` — MASESystem 总控台（façade 门面模式）
- **作用**：生命周期管理、agent 注册、background GC（后台垃圾回收）、atexit drain（退出时清理）
- **面试重点**：
  - `atexit.register(self._atexit_drain)` + `join_background_tasks(timeout=8.0)` → 优雅关闭：程序退出前等后台线程干完活，最多等 8 秒
  - `_agents = get_registry().build_all(...)` → 插件化注册：新增 Agent 不用改总控台，注册就行
- **关键行**：64-88（`__init__` 构造函数）、89-112（drain 排水/清理逻辑）

### `src/mase/protocol.py` — 消息宪法（protocol 协议）
- **作用**：AgentMessage frozen dataclass（不可变数据类），不可变消息协议
- **面试重点**：
  - `frozen=True`（冻结）：消息一旦发出就不可变，防止下游偷偷改 payload（载荷/数据内容）
  - `default_factory=dict`（默认工厂）：避免 Python 经典的"可变默认参数"坑
  - UTC isoformat（协调世界时标准格式）：时间戳不带时区歧义
- **关键行**：12-31（AgentMessage 定义）、34-49（make_message 工厂函数）
- **Show off（展示/炫技）理由**："消息一旦发出就不可变，防止下游偷偷改 payload"

### `src/mase/router.py` — 路由决策（router 路由器）
- **作用**：keyword fast-path（关键词快速通道）+ LLM router（大模型路由器）
- **面试重点**：
  - `MEMORY_TRIGGER_PHRASES`（记忆触发短语，43-49）：关键词快路径，包含"之前"、"上次"、"那个"等 15 个中文触发词
  - `keyword_router_decision`（关键词路由决策，52-57）：O(n) 字符串匹配，零 LLM 调用
  - `ROUTER_SYSTEM`（路由系统提示词，75-117）：LLM 系统提示
- **关键行**：43-57（fast path 快速通道）、75-117（LLM prompt 大模型提示词）

### `src/mase/notetaker_agent.py` — 记忆守门人（notetaker 记事员）
- **作用**：唯一有写权限的节点，Tool Calling（工具调用）操作记忆
- **面试重点**：
  - `NOTETAKER_TOOLS`（记事员工具集，41-106）：4 个 LLM 暴露工具（write_interaction, upsert_fact, search_memory, get_facts）
  - `_TRI_VAULT_BUCKET_BY_TOOL`（工具到三仓的映射表，25-30）：写入镜像到三仓（tri-vault）
  - `mase2_upsert_fact` 的 schema（结构）：category（类别）/key（键）/value（值）
- **关键行**：25-30（tri-vault mirror 三仓镜像）、41-106（tools schema 工具结构）、108-120（handlers 处理函数）

### `src/mase/planner_agent.py` — 任务分解（planner 计划员）
- **作用**：只做计划，不直接回答，≤4 步
- **面试重点**：`PLANNER_SYSTEM`（计划员系统提示词）硬性规则、fallback（兜底/回退）机制
- **关键行**：5-19（system prompt 系统提示词）、25-40（plan/fallback 计划与兜底）

### `src/mase/executor.py` — 最终回答（executor 执行器）
- **作用**：加载 memory context（记忆上下文）+ honesty（诚实）prompt（提示词）
- **面试重点**："If memory context does not contain... clarify that you don't have a specific memory"（如果记忆里没有，老实承认没有）
- **关键行**：10-40（execute 执行方法）

### `src/mase/langgraph_orchestrator.py` — LangGraph 编排（orchestrator 编排器）
- **作用**：StateGraph（状态图）连接 5 节点，支持 fast path（快速通道）
- **面试重点**：`AgentState`（智能体状态）7 个键、`router_node`（路由节点）双路径、`_fast_path_enabled`（快速通道是否开启）
- **关键行**：39-48（AgentState 智能体状态定义）、110-120（router_node 路由节点）

---

## 二、记忆与检索（技术深度区）

### `mase_tools/memory/api.py` — 记忆 API 门面（API 接口层）
- **作用**：所有外部调用的入口，`mase2_*` 系列函数
- **面试重点**：
  - `mase2_upsert_fact`（40-58）：覆盖式写入（upsert = update + insert）
  - `mase2_correct_and_log`（94-128）：端到端纠正 helper（helper 辅助函数）
  - `mase2_supersede_facts`（81-91）：批量标记旧事实为 superseded（被取代的/失效的）
- **关键行**：28-128（核心 API）

### `mase_tools/memory/db_core.py` — SQLite 底座（core 核心）
- **作用**：SQL 操作、schema migration（表结构迁移）、连接管理
- **面试重点**：
  - `resolve_db_path`（116-131）：路径解析链，5 级搜索
  - `_ensure_schema`（173-200）：schema 版本管理，确保表结构是最新的
  - 搜 `CREATE TABLE`：events（事件流水表）/ entity_state（实体状态表）/ session_context（会话上下文表）定义
- **关键行**：116-162（路径解析）、173-200（schema 迁移）
- **提示**：文件有 1836 行，不用全读，只看 schema 定义和 CRUD（增删改查）函数签名

### `mase_tools/memory/tri_vault.py` — 三仓 Markdown 镜像（tri 三，vault 仓库）
- **作用**：SQLite 写入同步镜像到 JSON 文件（context/sessions/state）
- **面试重点**：
  - `mirror_write`（101-154）：原子写（atomic write，tmp 临时文件 + os.replace 原子替换）
  - `_target_lock`（161-168）：per-file threading.Lock（每个文件一把锁）
  - Windows 重试机制：`os.replace` 失败重试 3 次（因为 Windows 文件占用很敏感）
- **关键行**：36-38（is_enabled 是否开启）、101-154（mirror_write 镜像写入）

### `mase_tools/memory/correction_detector.py` — 纠正检测器（correction 纠正，detector 检测器）
- **作用**：检测用户是否在说"我之前说错了"
- **面试重点**：
  - `_TRIGGER_PATTERNS`（触发模式，14-33）：中英文正则触发词（regular expression 正则表达式，一种模式匹配语法）
  - `_STRIP_PATTERNS`（去触发词模式，36-51）：去触发词保留主题词
  - `extract_keywords_for_supersede`（91-121）：主题词抽取
- **关键行**：14-33（triggers 触发器）、68-88（detect_correction 检测纠正）

### `src/mase/fact_sheet.py` — 长上下文 Fact Sheet（事实表）构建
- **作用**：把检索结果压缩成证据文本
- **面试重点**：三档配置（long_memory 长记忆/multidoc 多文档/single 单文档）、`extract_focused_window`（提取焦点窗口）、char_budget（字符预算）
- **关键行**：19-85（build_long_context_fact_sheet 构建长上下文事实表）

### `src/mase/fact_sheet_long_memory.py` — LongMemEval 专用 Fact Sheet
- **作用**：比普通的 fact_sheet 更复杂，有 priority_rows（优先行）+ halo_rows（光环行/上下文行）+ evidence_scan（证据扫描）
- **面试重点**：
  - `char_budget = 220_000`（默认字符预算）、local_only 时压缩到 12_000（因为本地 7B 模型上下文只有 16k token，约 65k 字符）
  - `priority_ids` + `max_session_halo_per_session=6`：相关行 + 上下文光环（每会话最多带 6 条邻居）
- **关键行**：26-185（build_long_memory_full_fact_sheet 构建长记忆完整事实表）

### `src/mase/hybrid_recall.py` — 混合召回（hybrid 混合，recall 召回）
- **作用**：BM25 + Dense + Temporal 三路融合
- **面试重点**：
  - 公式：`score = α*dense + β*bm25 + γ*temporal`
  - `_InlineBM25`（120-150）：纯 Python BM25 fallback（fallback 后备/降级方案）
  - `_minmax_normalize`（107-114）：min-max 归一化策略（把数据压到 0-1 之间）
  - `_detect_temporal_window`（60-77）：时间词检测（"昨天/上周/上个月"）
- **关键行**：8-12（公式）、60-77（temporal 时间维度）、107-150（BM25）
- **Show off 理由**："三路分别归一化后再加权，避免某一路数值范围压制其他路"

### `src/mase/multipass_retrieval.py` — 多轮检索（multi-pass 多轮，retrieval 检索）
- **作用**：query rewrite（查询改写）+ HyDE + cross-encoder rerank（交叉编码器重排序）+ safety net（安全网）
- **面试重点**：
  - `_generate_query_variants_cached`（86-116）：小模型改写 + LRU cache（Least Recently Used 最近最少使用缓存）
  - `_generate_hyde_keywords_cached`（119-147）：HyDE（Hypothetical Document Embedding，假设文档嵌入）——让小模型起草假想答案，提取关键词再检索
  - safety net（安全网/兜底）：multipass 召回 < baseline（基线）一半时回退
- **关键行**：28-60（env 开关）、86-147（rewrite + HyDE）

### `src/mase/mode_selector.py` — 模式选择器（mode 模式，selector 选择器）
- **作用**：任务分桶、长度桶映射、multipass 允许判断
- **面试重点**：
  - `long_context_search_limit`（61-69）：16k→12, 32k→15, ..., 256k→30（搜多少条）
  - `long_context_window_radius`（72-80）：16k→240, ..., 256k→420（每条保留多少字）
  - `multipass_allowed_for_task`（83-95）：只有 long_context_qa（长上下文问答）和 long_memory（长记忆）才开 multipass，闲聊不开
- **关键行**：61-95（长度桶和 multipass 门控）

### `src/mase/reasoning_engine.py` — 推理工作区（reasoning 推理）
- **作用**：`ReasoningWorkspace` frozen dataclass（不可变数据类），operation（操作类型）分类
- **面试重点**：
  - `_classify_operation`（121-141）：lookup（查找）/update（更新）/difference（差异）/duration（时长）/money（金额）/count（计数）/chronology（时间顺序）/disambiguation（消歧）
  - `ReasoningWorkspace`（56-67）：10 个字段
- **关键行**：56-67（dataclass 数据类定义）、121-141（classifier 分类器）

---

## 三、Eval 体系（评估体系，反刷榜区）

### `benchmarks/runner.py` — 评测发动机（runner 运行器）
- **作用**：per-case memory isolation（每用例记忆隔离）、config profile（配置档案）、call log aggregation（调用日志聚合）
- **面试重点**：
  - `_aggregate_call_log`（106-131）：按 agent 统计调用次数/耗时/token
  - `_summarize_sample_shapes`（143-150）：样本形状统计
  - dataset fingerprint（数据集指纹）：sample_ids_sha256（样本ID的SHA-256哈希）
- **关键行**：106-131（aggregation 聚合）、143-150（shapes 形状）
- **提示**：文件 1044 行，只看前 150 行即可理解框架

### `benchmarks/llm_judge.py` — 保守评委（judge 评委/裁判）
- **作用**：LLM-as-judge（用大模型当评委），只升级不降级
- **面试重点**：
  - `_JUDGE_SYSTEM`（36-46）：评委系统提示词
  - `judge_answer`（78-109）：缓存 + 调用模型
  - `_parse_verdict`（112-120）：JSON 解析容错（容错 = 出错了也能处理）
- **关键行**：36-46（system prompt 系统提示词）、78-109（主函数）

### `benchmarks/scoring.py` — 分数计算（scoring 评分）
- **作用**：substring match（子串匹配）+ keyword match（关键词匹配）+ math（数学）+ code generation（代码生成）
- **面试重点**：
  - `_contains_phrase`（100-113）：多 variant（变体）匹配（normalize 归一化 + compact 压缩 + number words 数字词）
  - `_extract_choice`（116-137）：选择题答案提取（优先级：FINAL ANSWER > ANSWER > last line 最后一行 > first match 第一个匹配）
- **关键行**：100-137（核心匹配逻辑）

### `docs/BENCHMARK_ANTI_OVERFIT.md` — 反过拟合政策（anti-overfit 反过拟合）
- **作用**：工程纪律文档，四大禁令
- **面试重点**：必须能背出至少两条禁令 + 解释为什么

---

## 四、工程基建（可靠性区）

### `src/mase/event_bus.py` — 事件总线（event bus 事件公共汽车）
- **作用**：pub/sub（发布订阅）、prefix matching（前缀匹配）、fire-and-forget（发完就忘）
- **面试重点**：sync delivery（同步投递）、subscriber（订阅者）异常不 crash engine（不崩引擎）、trace_id（追踪ID，用于关联整个调用链）
- **关键行**：42-48（Event dataclass 事件数据类）、61-117（subscribe/publish 订阅与发布）

### `src/mase/model_interface.py` — 模型统一接口（interface 接口）
- **作用**：多后端、config 解析链、cloud policy（云模型策略）
- **面试重点**：
  - `resolve_config_path`（24-43）：5 级配置搜索（传入参数 → env → 当前目录 → 项目根目录 → 用户家目录）
  - `_enforce_cloud_model_policy`（84-93）：默认阻止云模型调用，必须显式授权
- **关键行**：24-43（config 链）、84-93（cloud policy 云策略）

### `src/mase/health_tracker.py` — 健康追踪（health 健康，tracker 追踪器）
- **作用**：EWMA（指数加权移动平均）成功率、latency（延迟）、cooldown（冷却）
- **面试重点**：
  - `_EWMA_ALPHA = 0.3`：新样本权重 30%，旧样本权重指数衰减
  - `record_success` / `record_failure`：更新 EWMA
  - `sort_candidates`：按健康分排序，cooldown（冷却中）的候选排到后面
- **关键行**：36-39（常量）、95-121（record 记录）、124-135（score 打分）

### `src/mase/circuit_breaker.py` — 熔断器（circuit breaker 电路断路器，借用到软件里叫熔断器）
- **作用**：closed（闭合/正常）/ open（断开/熔断）/ half_open（半开/试探）状态封装
- **面试重点**：基于 health_tracker 的 cooldown 逻辑，不是独立状态机。为什么不用 pybreaker？因为已经有 health tracker，再加一层会引入第二状态源。这个 wrapper（包装器）只有 50 行。
- **关键行**：30-72（BreakerState 熔断状态 + state_for 状态查询）

### `src/mase/adaptive_verify.py` — 自适应验证（adaptive 自适应的，verify 验证）
- **作用**：skip（跳过）/ single（单校验器）/ dual（双校验器投票）三档决策
- **面试重点**：
  - `DEFAULT_SKIP_THRESHOLD = 0.85`（默认跳过阈值）
  - `DEFAULT_DUAL_THRESHOLD = 0.5`（默认双校验阈值）
  - `DEFAULT_DOMINANCE_GAP = 0.2`（默认优势差距）
  - `HARD_QTYPES = {"multi-session", "temporal-reasoning"}`（硬问题类型：多会话、时间推理）
- **关键行**：26-31（常量）、60-80（__init__ 构造函数）、91-98（top gap 顶部差距）

---

## 五、容易被忽略但面试可能问到的文件

### `src/mase/topic_threads.py` — 话题线程 + 语言检测
- **作用**：`detect_text_language`（检测文本语言，中文/英文）决定用哪个版本的 prompt 和候选表
- **面试点**：MASE 是双语项目，中文用 CJK 候选表，英文用普通候选表

### `src/mase/answer_normalization.py` — 答案归一化
- **作用**：从模型回答里提取标准答案（选择题 A/B/C/D、数字、日期等）
- **面试点**：benchmark 评分前要先做 answer normalization，不然"答案：A"和"A"会被判为不同

### `src/mase/config_schema.py` — 配置结构验证
- **作用**：用 Pydantic v2 验证 `config.json` 的合法性
- **面试点**：配置错了早期报错，不等到运行时才崩

### `benchmarks/baseline.py` — 裸模型基线
- **作用**：同一个模型不加 MASE 直接跑 benchmark，算 delta（提升量）
- **面试点**：88.71% 不是绝对值，是"裸模型 4.84% → +84pp"的 delta

### `benchmarks/schemas.py` — Benchmark 数据结构
- **作用**：`BenchmarkSample` dataclass，定义了题目/答案/类型/元数据
- **面试点**：强类型 schema 保证 benchmark 数据格式一致

### `benchmarks/adapters.py` — 外部 Benchmark 适配器
- **作用**：把 NoLiMa/BAMBOO/LV-Eval 的不同格式转成 MASE 内部格式
- **面试点**：Adapter 模式，新增 benchmark 只需要写 adapter，不用改 runner

---

## 六、集成与前端（了解即可）

### `integrations/` — 外接生态（integration 集成）
- `langchain/mase_memory.py`：LangChain `BaseChatMemory`（基础聊天记忆）适配器
- `llamaindex/`：LlamaIndex `BaseMemory` 适配器
- `mcp/server.py`：MCP（Model Context Protocol，模型上下文协议）Server 暴露工具

### `frontend/` — React 可视化前端
- 技术栈：React（前端框架）+ Vite（构建工具）+ TypeScript（类型化 JavaScript）
- 面试时如果问到："这是给记忆做可视化管理的平台，Vite 构建，通过 OpenAI-compatible API（兼容 OpenAI 的接口）和后端通信"

---

## 七、面试时快速定位指南

| 面试官说 | 你打开的文件 | 指到的行 |
|---------|------------|---------|
| "给我看看消息协议" | `src/mase/protocol.py` | 12-31 |
| "Router 怎么工作的" | `src/mase/router.py` | 43-57, 75-117 |
| "怎么防止下游改消息" | `src/mase/protocol.py` | 12 (`frozen=True`) |
| "三路召回公式在哪" | `src/mase/hybrid_recall.py` | 8-12 |
| "BM25 自己实现的吗" | `src/mase/hybrid_recall.py` | 120-150 |
| "保守 judge 策略" | `benchmarks/llm_judge.py` | 36-46 |
| "反过拟合怎么做的" | `docs/BENCHMARK_ANTI_OVERFIT.md` | 全文 |
| "优雅关闭怎么做的" | `src/mase/engine.py` | 89-112 |
| "tri-vault 原子写" | `mase_tools/memory/tri_vault.py` | 101-154 |
| "纠正检测" | `mase_tools/memory/correction_detector.py` | 14-33 |
| "cloud policy" | `src/mase/model_interface.py` | 84-93 |
| "熔断器" | `src/mase/circuit_breaker.py` | 30-72 |
| "双语支持" | `src/mase/topic_threads.py` | 搜 `detect_text_language` |
| "答案提取" | `src/mase/answer_normalization.py` | 搜 `extract_answer` |
| "裸模型基线" | `benchmarks/baseline.py` | 前 50 行 |

---

> **Kimi 备注**：本地图覆盖了你面试 95% 可能需要指出的代码位置。如果面试官问到你没准备的文件，冷静地说"这个功能在 X 模块里，具体实现我确认一下"，然后快速 grep（全局搜索）关键词定位。
