# MASE 平台能力矩阵：Memory Operations UI 现状与缺口

## 当前定位

MASE 当前更准确的定位是 **Memory Operations UI**：用于查看、验证、治理和演示 MASE 记忆能力，覆盖本地 FastAPI 后端与 React 前端的核心记忆操作链路。它可以支撑 SaaS 接入前的运营自检、白盒调试和人工治理，但 **不替代独立观测平台**。完整的 APM、集中日志、告警、SLO、长周期指标留存和跨服务链路分析应交给 SaaS 侧或专用观测平台承接。

## 检查范围

本矩阵基于以下文件与目录的现状审计：

- `frontend/src/App.tsx`
- `frontend/src/pages/*.tsx`
- `frontend/src/api.ts`
- `integrations/openai_compat/server.py`
- `src/mase/metrics.py`
- `src/mase/health_tracker.py`
- `src/mase/trace_recorder.py`
- `src/mase/event_bus.py`
- `README.md`
- `docs/`

## 六大审计缺口与归属

以下 6 项是本轮审计要求必须显式跟踪的缺口。它们不等价于 Phase 1 全部阻塞项，归属如下：

| 缺口 | 当前状态 | 明确归属 | Phase 1 是否阻塞 | 说明 |
| --- | --- | --- | --- | --- |
| trace 历史列表 | Trace Studio 只支持单次 `runTrace` 展示，没有历史列表、筛选、对比、回放。 | MASE Memory Ops 可补最小历史入口；完整跨服务 trace 检索归独立观测平台。 | 不阻塞，除非 SaaS 要求内置审计留痕。 | Phase 1 只需要单次 trace 可追溯和 record path/trace id 清楚。 |
| 模型调用耗时 / 失败率 | `health_tracker.py` 和 `metrics.py` 有后端基础数据，但 Dashboard 未产品化展示。 | MASE 后端基础能力；SaaS 可消费最小健康摘要；完整时序图归独立观测平台。 | 不阻塞。 | Phase 2 可做模型健康视图或接入观测平台。 |
| event bus / metrics 可视化 | `event_bus.py` 和 `metrics.py` 存在后端机制，没有 event bus 页面或实时指标大屏。 | 后端基础能力归 MASE；实时可视化和跨服务指标归独立观测平台。 | 不阻塞。 | 不能把 in-process event bus 写成外部观测系统。 |
| 自动刷新 | Dashboard、Timeline 等页面主要是加载/手动刷新模式，没有系统性自动刷新。 | MASE UI 体验增强。 | 不阻塞。 | Phase 3 可加局部刷新、刷新时间戳和错误恢复。 |
| 告警状态 | 没有告警规则、通知路由、值班升级或告警状态页面。 | 独立观测平台负责；MASE 仅提供健康/metrics 基础信号。 | 不阻塞。 | 不应在 MASE Memory Ops 中承诺完整告警。 |
| 只读审计模式 | 已补 `MASE_READ_ONLY` 后端强制保护，并在前端展示只读状态、禁用持久写入按钮。 | SaaS 接入层仍应 enforce；MASE UI 已提供本地只读模式。 | 已解除本地 UI 阻塞。 | SaaS 前端嵌入前仍需按部署环境复核鉴权和只读策略。 |

## 页面能力矩阵

| 页面 | 前端入口 | 已覆盖能力 | 当前缺口 | SaaS Phase 1 影响 |
| --- | --- | --- | --- | --- |
| Dashboard | `DashboardPage.tsx`，导航文案“运营 cockpit” | 调用 `health`、`bootstrap`、`dashboard`、`validate`；展示 facts、events、procedures、snapshots、threads、校验结果、近期活动、系统地图和基础图表。 | 未展示模型调用耗时、失败率、候选模型健康、event bus 指标；无自动刷新；无告警状态。 | 作为 Memory Operations 总览足够；完整观测图表、告警和自动刷新不阻塞 Phase 1。 |
| Trace Studio | `ChatPage.tsx`，导航 key 为 `chat` | 支持 OpenAI-compatible chat；支持 `runTrace` 展示单次路由/审计链；默认 dry-run，显式勾选才写入，且只读模式下强制 dry-run。 | 没有 trace 历史列表、筛选、对比；模型耗时/失败率未可视化。 | 写记忆边界已清楚；历史列表和高级分析不阻塞。 |
| Recall Lab | `RecallPage.tsx` | 支持 recall、current-state、explain；可控制 top_k 与是否包含历史；用于召回证据检查。 | 没有批量回归、召回质量趋势、自动评测入口。 | 单租户/单 scope 调试可用；质量趋势不阻塞 Phase 1。 |
| Fact Center | `FactsPage.tsx` | 支持 facts 列表、upsert、history、archive/delete；按 category 过滤；保留治理原因；只读模式禁用写入/归档。 | 缺少批量导入导出、冲突策略可视化。 | 事实治理基础可用；SaaS 仍需复核部署级强隔离。 |
| Timeline Ops | `TimelinePage.tsx` | 支持 timeline 查询、events 写入、corrections 纠错、snapshots 列表、consolidate 快照。 | 缺少事件流式订阅、时间轴 diff、自动刷新、纠错审批状态。 | 人工运营可用；自动刷新和审批 UI 不阻塞 Phase 1。 |
| Session Vault | `SessionsPage.tsx` | 支持 session-state 查询、upsert、forget；支持 include_expired 与 TTL。 | scope 隔离边界、租户/工作区跨越保护、批量清理策略未在 UI 明确表达。 | scope 隔离不明会阻塞 Phase 1；高级批量治理不阻塞。 |
| Procedure Hub | `ProceduresPage.tsx` | 支持 procedures 列表与注册；可按 procedure_type 过滤。 | 缺少版本化、启停状态、审批流、执行命中统计。 | 基础规则记忆可用；版本/审批能力不阻塞 Phase 1。 |

## API 能力矩阵

| 能力 | 前端封装 / 端点 | 后端路由 | 当前用途 | 状态与缺口 |
| --- | --- | --- | --- | --- |
| health | `api.health()` / `GET /health` | `health()` | 服务存活与基础健康检查。 | 已暴露；需纳入 SaaS 接入健康探针。 |
| bootstrap | `api.bootstrap()` / `GET /v1/ui/bootstrap` | `ui_bootstrap()` | UI 初始化、profile templates、模型描述、产品信息、前端静态资源状态。 | 已暴露；适合作为 UI 启动前置检查。 |
| dashboard | `api.dashboard(scope)` / `GET /v1/ui/dashboard` | `ui_dashboard()` | 聚合 KPI、图表、近期活动、系统地图、校验结果。 | 已暴露；不包含 metrics、health_tracker 的模型健康和 event bus 视图。 |
| chat | `api.chat(messages)` / `POST /v1/chat/completions` | `chat_completions()` | OpenAI-compatible chat 调用，便于 SaaS 适配。 | 已暴露；需要验证失败格式、流式行为和 SaaS SDK 兼容性。 |
| runTrace | `api.runTrace(query, log)` / `POST /v1/mase/run` | `run_mase()` | 单次 MASE trace 执行与审计链展示。 | 已暴露；默认 dry-run，`log=true` 才写入，只读模式拒绝持久写入。 |
| recall | `api.recall()` / `POST /v1/memory/recall` | `memory_recall()` | 查询历史与事实召回。 | 已暴露；需要稳定错误语义和 scope 过滤验证。 |
| current-state | `api.currentState()` / `POST /v1/memory/current-state` | `memory_current_state()` | 查询当前事实状态。 | 已暴露；需要与 recall 结果区分清晰。 |
| events | `api.writeEvent()` / `POST /v1/memory/events` | `memory_event()` | 写入 timeline 事件。 | 已暴露；`MASE_READ_ONLY` 会后端拒绝写入。 |
| corrections | `api.correctMemory()` / `POST /v1/memory/corrections` | `memory_correction()` | 写入记忆纠错事件。 | 已暴露；缺少审批状态与只读保护。 |
| facts | `api.facts()`、`api.upsertFact()`、`api.forgetFact()` / `GET|POST|DELETE /v1/memory/facts...` | `memory_facts()`、`memory_fact_upsert()`、`memory_fact_forget()` | 事实查询、写入、归档/删除。 | 已暴露；需要验证租户和 workspace 过滤不可绕过。 |
| history | `api.factHistory()` / `GET /v1/memory/facts/history` | `memory_fact_history()` | 查看事实历史版本。 | 已暴露；可支撑人工审计，不是完整审计日志平台。 |
| session | `api.getSessionState()`、`api.upsertSessionState()`、`api.forgetSessionState()` / `/v1/memory/session-state` | `memory_session_state_get()`、`memory_session_state_upsert()`、`memory_session_state_forget()` | 短期上下文查询、写入、遗忘。 | 已暴露；scope 隔离与 TTL 语义需作为 Phase 1 验收重点。 |
| procedures | `api.procedures()`、`api.registerProcedure()` / `/v1/memory/procedures` | `memory_procedures()`、`memory_procedure_register()` | 过程/规则记忆查询与注册。 | 已暴露；缺少版本、启停、命中统计。 |
| snapshots | `api.snapshots()`、`api.consolidate()` / `/v1/memory/snapshots`、`/consolidate` | `memory_snapshots()`、`memory_snapshot_consolidate()` | episodic snapshots 查询与合并。 | 已暴露；缺少快照差异与回滚 UI。 |
| validate | `api.validate(scope)` / `GET /v1/memory/validate` | `memory_validate()` | 记忆系统校验。 | 已暴露；前端可见，测试应保持通过。 |
| explain | `api.explain()` / `POST /v1/memory/explain` | `memory_explain()` | 召回解释与证据说明。 | 已暴露；适合 Phase 1 调试和人工验收。 |

## 后端基础设施（backend foundation, not frontend-ready）

本节列出的模块是 MASE 后端基础设施。它们证明 MASE 有可扩展的 metrics、health、trace、event 基础，但 **不能被描述为前端已产品化能力**。是否接入 UI 或交给独立观测平台，需要按上方归属表推进。

| 后端能力 | 文件 | 已有基础 | 前端暴露情况 | 缺口 |
| --- | --- | --- | --- | --- |
| metrics | `src/mase/metrics.py` | 订阅 event bus，维护事件计数、平均延迟、candidate health 快照，并支持 Prometheus 文本格式。 | Dashboard 未直接展示 event counters、latency、candidate failures；未见专门 metrics 页面。 | 需要 API/页面接入，或交给观测平台采集。 |
| health_tracker | `src/mase/health_tracker.py` | 记录 provider/model 成功、失败、EWMA latency、cooldown，并发布 `mase.health.success/failure`。 | UI 未展示候选模型健康、失败率、冷却状态。 | 模型调用耗时/失败率可作为 Phase 2 运维能力，不是 Phase 1 必需项。 |
| trace_recorder | `src/mase/trace_recorder.py` | 可通过 `MASE_TRACE_RECORD_PATH` 记录 trace payload，并支持加载历史 trace 文件。 | Trace Studio 只展示当前单次 trace，没有历史列表。 | trace 历史列表是需要项，但不阻塞 Phase 1，除非 SaaS 要求内置审计留痕。 |
| event bus | `src/mase/event_bus.py` | 进程内同步 pub/sub，支持 topic/prefix 订阅，订阅者异常隔离。 | 没有事件流页面、实时订阅、event bus 健康视图。 | 可作为内部扩展点；完整可视化交给 Phase 2/观测平台。 |

## 缺口分级

### Phase 1 阻塞项

这些问题会影响 SaaS 接入的正确性、安全边界或基本可用性，必须在 Phase 1 验收前关闭：

1. **memory API 不稳定**：recall、current-state、facts、session、procedures、snapshots、validate、explain 的响应结构、错误结构、状态码和兼容性必须稳定。
2. **scope 隔离不明**：tenant_id、workspace_id、visibility 必须在所有读写路径上统一生效，不能被 query/body 差异绕过。
3. **trace 写记忆边界**：Trace Studio 已默认 dry-run；SaaS 只读审计、演示或排障场景仍必须验证部署环境不会绕过 `MASE_READ_ONLY`。
4. **前端白屏**：Dashboard、Trace Studio、Recall Lab、Fact Center、Timeline Ops、Session Vault、Procedure Hub 任一核心页面白屏都会阻塞演示与运营验收。
5. **测试不绿**：与 memory API、OpenAI-compatible chat、UI API 相关的既有测试必须通过，避免 SaaS 接入建立在不稳定基线上。

### Phase 2 需要项

这些能力会提升 SaaS 运维闭环，但不应阻塞 Phase 1 的最小可用接入：

1. trace 历史列表、筛选、导出和对比。
2. 模型调用耗时、失败率、cooldown 状态、候选模型健康视图。
3. metrics API 或 Prometheus scrape 集成说明。
4. event bus topic 统计、订阅者状态和错误队列可见性。
5. 只读审计模式已具备本地产品化开关与前端提示；后续只需纳入 SaaS 部署策略。
6. 事实、session、procedure 的批量治理能力。

### Phase 3 UI 项

这些主要是体验与效率增强，可在 SaaS 接入稳定后推进：

1. Dashboard 自动刷新、手动刷新时间戳、局部加载状态。
2. Timeline 实时流、diff、纠错审批状态。
3. Fact Center 批量导入导出、冲突合并 UI。
4. Procedure Hub 版本管理、启停状态、命中统计图。
5. Session Vault 批量清理、TTL 风险提示。
6. 更完整的图表筛选、钻取、空状态与错误恢复体验。

### 非目标 / 交给观测平台

MASE Memory Operations UI 不应承担以下完整观测平台职责：

1. 全量 APM、跨服务分布式追踪、日志集中检索。
2. 告警规则引擎、通知路由、值班升级、SLO burn-rate。
3. 长周期指标留存、容量规划、成本归因报表。
4. 多服务拓扑、基础设施监控、数据库/队列深度监控。
5. 生产级安全审计日志归档与合规报表。

## SaaS Phase 1 明确边界

**不阻塞 SaaS Phase 1**：完整观测图表、告警、自动刷新、trace 历史高级检索、event bus 可视化、模型健康大屏、批量治理、审批流、长期留存报表。

**会阻塞 SaaS Phase 1**：memory API 不稳定、scope 隔离不明、部署级只读/写入边界不可验证、核心前端页面白屏、既有测试不绿。

## 建议验收口径

1. 将 MASE 作为 SaaS 的 Memory Operations UI 接入，而不是作为 SaaS 的唯一观测平台。
2. Phase 1 以 API 稳定性、scope 隔离、只读/写入边界、核心页面可用性和测试通过作为准入标准。
3. Phase 2 再把 metrics、health_tracker、trace_recorder、event bus 逐步接入 UI 或外部观测系统。
4. Phase 3 聚焦运营效率和可视化体验，不反向扩大 Phase 1 范围。
