# MASE 源码地图

> ⚠️ **Kimi 生成文件**：本文件由 Kimi 逐行阅读源码后整理，标注了每个文件的作用、面试重点、关键行号。
> 🎯 用途：面试时快速定位代码，回答"给我看看 XX 的实现"。

---

## 一、架构核心（面试最高频）

### `src/mase/engine.py` — MASESystem 总控台
- **作用**：生命周期管理、agent 注册、background GC、atexit drain
- **面试重点**：
  - `atexit.register(self._atexit_drain)` + `join_background_tasks(timeout=8.0)` → 优雅关闭
  - `_agents = get_registry().build_all(...)` → 插件化注册
- **关键行**：64-88（`__init__`）、89-112（drain）

### `src/mase/protocol.py` — 消息宪法
- **作用**：AgentMessage frozen dataclass，不可变消息协议
- **面试重点**：`frozen=True`、`default_factory=dict`、UTC isoformat
- **关键行**：12-31（AgentMessage）、34-49（make_message）
- **Show off 理由**："消息一旦发出就不可变，防止下游偷偷改 payload"

### `src/mase/router.py` — 路由决策
- **作用**：keyword fast-path + LLM router
- **面试重点**：
  - `MEMORY_TRIGGER_PHRASES`（43-49）：关键词快路径
  - `keyword_router_decision`（52-57）：O(n) 字符串匹配
  - `ROUTER_SYSTEM`（75-117）：LLM 系统提示
- **关键行**：43-57（fast path）、75-117（LLM prompt）

### `src/mase/notetaker_agent.py` — 记忆守门人
- **作用**：唯一有写权限的节点，Tool Calling 操作记忆
- **面试重点**：
  - `NOTETAKER_TOOLS`（41-106）：4 个 LLM 暴露工具
  - `_TRI_VAULT_BUCKET_BY_TOOL`（25-30）：写入镜像到三仓
  - `mase2_upsert_fact` 的 schema：category/key/value
- **关键行**：25-30（tri-vault mirror）、41-106（tools schema）、108-120（handlers）

### `src/mase/planner_agent.py` — 任务分解
- **作用**：只做计划，不直接回答，≤4 步
- **面试重点**：`PLANNER_SYSTEM` 硬性规则、fallback 机制
- **关键行**：5-19（system prompt）、25-40（plan/fallback）

### `src/mase/executor.py` — 最终回答
- **作用**：加载 memory context + honesty prompt
- **面试重点**："If memory context does not contain... clarify that you don't have a specific memory"
- **关键行**：10-40（execute 方法）

### `src/mase/langgraph_orchestrator.py` — LangGraph 编排
- **作用**：StateGraph 连接 5 节点，支持 fast path
- **面试重点**：`AgentState` 7 个键、`router_node` 双路径、`_fast_path_enabled`
- **关键行**：39-48（AgentState）、110-120（router_node）

---

## 二、记忆与检索（技术深度区）

### `mase_tools/memory/api.py` — 记忆 API 门面
- **作用**：所有外部调用的入口，`mase2_*` 系列函数
- **面试重点**：
  - `mase2_upsert_fact`（40-58）：覆盖式写入
  - `mase2_correct_and_log`（94-128）：端到端纠正 helper
  - `mase2_supersede_facts`（81-91）：批量标记旧事实为 superseded
- **关键行**：28-128（核心 API）

### `mase_tools/memory/db_core.py` — SQLite 底座
- **作用**：SQL 操作、schema 迁移、连接管理
- **面试重点**：
  - `resolve_db_path`（116-131）：路径解析链
  - `_ensure_schema`（173-200）：schema 版本管理
  - 搜 `CREATE TABLE`：events / entity_state / session_context 定义
- **关键行**：116-162（路径解析）、173-200（schema 迁移）
- **提示**：文件有 1836 行，不用全读，只看 schema 定义和 CRUD 函数签名

### `mase_tools/memory/tri_vault.py` — 三仓 Markdown 镜像
- **作用**：SQLite 写入同步镜像到 JSON 文件（context/sessions/state）
- **面试重点**：
  - `mirror_write`（101-154）：原子写（tmp + os.replace）
  - `_target_lock`（161-168）：per-file threading.Lock
  - Windows 重试机制：`os.replace` 失败重试 3 次
- **关键行**：36-38（is_enabled）、101-154（mirror_write）

### `mase_tools/memory/correction_detector.py` — 纠正检测器
- **作用**：检测用户是否在说"我之前说错了"
- **面试重点**：
  - `_TRIGGER_PATTERNS`（14-33）：中英文正则触发词
  - `_STRIP_PATTERNS`（36-51）：去触发词保留主题词
  - `extract_keywords_for_supersede`（91-121）：主题词抽取
- **关键行**：14-33（triggers）、68-88（detect_correction）

### `src/mase/fact_sheet.py` — 长上下文 Fact Sheet 构建
- **作用**：把检索结果压缩成证据文本
- **面试重点**：三档配置（long_memory/multidoc/single）、`extract_focused_window`、char_budget
- **关键行**：19-85（build_long_context_fact_sheet）

### `src/mase/fact_sheet_long_memory.py` — LongMemEval 专用 Fact Sheet
- **作用**：比普通的 fact_sheet 更复杂，有 priority_rows + halo_rows + evidence_scan
- **面试重点**：
  - `char_budget = 220_000`（默认）、local_only 时压缩到 12_000
  - `priority_ids` + `max_session_halo_per_session=6`：相关行 + 上下文光环
- **关键行**：26-185（build_long_memory_full_fact_sheet）

### `src/mase/hybrid_recall.py` — 混合召回
- **作用**：BM25 + Dense + Temporal 三路融合
- **面试重点**：
  - 公式：`score = α*dense + β*bm25 + γ*temporal`
  - `_InlineBM25`（120-150）：纯 Python BM25 fallback
  - `_minmax_normalize`（107-114）：归一化策略
  - `_detect_temporal_window`（60-77）：时间词检测
- **关键行**：8-12（公式）、60-77（temporal）、107-150（BM25）
- **Show off 理由**："三路分别归一化后再加权，避免某一路数值范围压制其他路"

### `src/mase/multipass_retrieval.py` — 多轮检索
- **作用**：query rewrite + HyDE + cross-encoder rerank + safety net
- **面试重点**：
  - `_generate_query_variants_cached`（86-116）：小模型改写 + LRU cache
  - `_generate_hyde_keywords_cached`（119-147）：假想答案提取关键词
  - safety net：multipass 召回 < baseline 一半时回退
- **关键行**：28-60（env 开关）、86-147（rewrite + HyDE）

### `src/mase/mode_selector.py` — 模式选择器
- **作用**：任务分桶、长度桶映射、multipass 允许判断
- **面试重点**：
  - `long_context_search_limit`（61-69）：16k→12, 32k→15, ..., 256k→30
  - `long_context_window_radius`（72-80）：16k→240, ..., 256k→420
  - `multipass_allowed_for_task`（83-95）：只有 long_context_qa 和 long_memory 才开 multipass
- **关键行**：61-95（长度桶和 multipass 门控）

### `src/mase/reasoning_engine.py` — 推理工作区
- **作用**：`ReasoningWorkspace` frozen dataclass，operation 分类
- **面试重点**：
  - `_classify_operation`（121-141）：lookup/update/difference/duration/money/count/chronology/disambiguation
  - `ReasoningWorkspace`（56-67）：10 个字段
- **关键行**：56-67（dataclass）、121-141（classifier）

---

## 三、Eval 体系（反刷榜区）

### `benchmarks/runner.py` — 评测发动机
- **作用**：per-case memory isolation、config profile、call log aggregation
- **面试重点**：
  - `_aggregate_call_log`（106-131）：按 agent 统计调用次数/耗时/token
  - `_summarize_sample_shapes`（143-150）：样本形状统计
  - dataset fingerprint：sample_ids_sha256
- **关键行**：106-131（aggregation）、143-150（shapes）
- **提示**：文件 1044 行，只看前 150 行即可理解框架

### `benchmarks/llm_judge.py` — 保守评委
- **作用**：LLM-as-judge，只升级不降级
- **面试重点**：
  - `_JUDGE_SYSTEM`（36-46）：评委系统提示
  - `judge_answer`（78-109）：缓存 + 调用模型
  - `_parse_verdict`（112-120）：JSON 解析容错
- **关键行**：36-46（system prompt）、78-109（主函数）

### `benchmarks/scoring.py` — 分数计算
- **作用**：substring match + keyword match + math + code generation
- **面试重点**：
  - `_contains_phrase`（100-113）：多 variant 匹配（normalize + compact + number words）
  - `_extract_choice`（116-137）：选择题答案提取（FINAL ANSWER > ANSWER > last line > first match）
- **关键行**：100-137（核心匹配逻辑）

### `docs/BENCHMARK_ANTI_OVERFIT.md` — 反过拟合政策
- **作用**：工程纪律文档，四大禁令
- **面试重点**：必须能背出至少两条禁令 + 解释为什么

---

## 四、工程基建（可靠性区）

### `src/mase/event_bus.py` — 事件总线
- **作用**：pub/sub、prefix matching、fire-and-forget
- **面试重点**：sync delivery、subscriber 异常不 crash engine、trace_id
- **关键行**：42-48（Event dataclass）、61-117（subscribe/publish）

### `src/mase/model_interface.py` — 模型统一接口
- **作用**：多后端、config 解析链、cloud policy
- **面试重点**：
  - `resolve_config_path`（24-43）：5 级配置搜索
  - `_enforce_cloud_model_policy`（84-93）：默认阻止云模型调用
- **关键行**：24-43（config 链）、84-93（cloud policy）

### `src/mase/health_tracker.py` — 健康追踪
- **作用**：EWMA 成功率、latency、cooldown
- **面试重点**：
  - `_EWMA_ALPHA = 0.3`：新样本权重 30%
  - `record_success` / `record_failure`：更新 EWMA
  - `sort_candidates`：按健康分排序，cooldown 的候选排到后面
- **关键行**：36-39（常量）、95-121（record）、124-135（score）

### `src/mase/circuit_breaker.py` — 熔断器
- **作用**：closed / open / half_open 状态封装
- **面试重点**：基于 health_tracker 的 cooldown 逻辑，不是独立状态机
- **关键行**：30-72（BreakerState + state_for）

### `src/mase/adaptive_verify.py` — 自适应验证
- **作用**：skip / single / dual 三档决策
- **面试重点**：
  - `DEFAULT_SKIP_THRESHOLD = 0.85`
  - `DEFAULT_DUAL_THRESHOLD = 0.5`
  - `DEFAULT_DOMINANCE_GAP = 0.2`
  - `HARD_QTYPES = {"multi-session", "temporal-reasoning"}`
- **关键行**：26-31（常量）、60-80（__init__）、91-98（top gap）

---

## 五、集成与前端（了解即可）

### `integrations/` — 外接生态
- `langchain/mase_memory.py`：LangChain `BaseChatMemory` 适配器
- `llamaindex/`：LlamaIndex `BaseMemory` 适配器
- `mcp/server.py`：MCP Server 暴露工具

### `frontend/` — React 可视化
- 技术栈：React + Vite + TypeScript
- 面试时如果问到："这是给记忆做可视化管理的平台，Vite 构建，通过 OpenAI-compatible API 和后端通信"

---

## 六、面试时快速定位指南

| 面试官说 | 你打开的文件 | 指到的行 |
|---------|------------|---------|
"给我看看消息协议" | `src/mase/protocol.py` | 12-31 |
"Router 怎么工作的" | `src/mase/router.py` | 43-57, 75-117 |
"怎么防止下游改消息" | `src/mase/protocol.py` | 12 (`frozen=True`) |
"三路召回公式在哪" | `src/mase/hybrid_recall.py` | 8-12 |
"BM25 自己实现的吗" | `src/mase/hybrid_recall.py` | 120-150 |
"保守 judge 策略" | `benchmarks/llm_judge.py` | 36-46 |
"反过拟合怎么做的" | `docs/BENCHMARK_ANTI_OVERFIT.md` | 全文 |
"优雅关闭怎么做的" | `src/mase/engine.py` | 89-112 |
"tri-vault 原子写" | `mase_tools/memory/tri_vault.py` | 101-154 |
"纠正检测" | `mase_tools/memory/correction_detector.py` | 14-33 |
"cloud policy" | `src/mase/model_interface.py` | 84-93 |
"熔断器" | `src/mase/circuit_breaker.py` | 30-72 |

---

> **Kimi 备注**：本地图覆盖了你面试 90% 可能需要指出的代码位置。如果面试官问到你没准备的文件，冷静地说"这个功能在 X 模块里，具体实现我确认一下"，然后快速 grep 关键词定位。
