# MASE 可观测平台

> **Memory Reliability & Observability Platform**
> AI 记忆系统的可靠性控制台——不是增删改查后台，而是让你看清楚"记了什么、为什么记错、成本几何、哪里该修"的专业观测中心。

---

## 目录

- [平台定位](#平台定位)
- [核心价值](#核心价值)
- [架构概览](#架构概览)
- [功能模块](#功能模块)
  - [总览 Overview](#总览-overview)
  - [可靠性 Reliability](#可靠性-reliability)
  - [运营 Operations](#运营-operations)
  - [记忆 Memory](#记忆-memory)
- [快速启动](#快速启动)
- [目录结构](#目录结构)
- [技术栈](#技术栈)
- [配置说明](#配置说明)
- [安全与权限](#安全与权限)
- [常见问题](#常见问题)

---

## 平台定位

MASE（**M**emory-**A**ugmented **S**ession **E**ngine）是一套双百合（Dual-Lane）设计的 AI 长期记忆系统，由两个协作的记忆智能体负责事实写入、事件归档、会话管理和记忆召回。

**两个智能体已经可以自主完成所有增删改查**——那么，为什么还需要一个可观测平台？

因为记忆系统最难的问题不是"怎么改"，而是"**为什么记错了？记错发生在哪一步？成本是谁产生的？这个拒答该不该拒？**"

| 传统后台 | MASE 可观测平台 |
|----------|----------------|
| 手动 CRUD | 智能体自主增删改查，人类观察 |
| 看数据 | 看**链路**：写入 → 事实 → 召回 → 答案 |
| 知道"记了什么" | 知道"**为什么**记对/记错" |
| 单点操作 | 全链路 Trace + Repair 工作流 |
| 无成本感知 | Token 费用逐笔可见，覆盖率可审计 |

---

## 核心价值

```
你想回答的问题              平台提供的功能
─────────────────────────────────────────────────────────────────
记了什么？                  Fact Center / Timeline / Session Vault
为什么没记住？              Why Not Remembered（事件→事实链路诊断）
为什么召回了这条？          Recall Lab（命中解释 + 证据链）
答案有没有记忆支撑？        Answer Support（证据跨度 + 支撑度）
这条拒答合理吗？            Refusal Quality（over_refusal 检测）
记忆有没有漂移？            Drift Detector（冲突 / 重复 / 过时压力）
系统现在健康吗？            Memory Observatory（模型健康 + 事件计数器）
云端 API 花了多少？         Cost Center（Token 成本 + 覆盖率 + 预算告警）
谁修改过记忆？              Audit Log（写入 / 删除 / 权限操作全追踪）
有没有误触敏感信息？        Privacy Guard（脱敏扫描 + 预览）
怎么触发一次可控修复？      Repair Center（Diff → Sandbox → 审批 → 执行）
整体可靠性水平？            SLO Dashboard + Golden Tests + Incidents
```

---

## 架构概览

```
┌────────────────────────────────────────────────────────────────┐
│                         Browser / UI                           │
│   React + TypeScript · Vite · 22 页面 · 中/英双语切换         │
└──────────────────────────────┬─────────────────────────────────┘
                               │ HTTP / REST
┌──────────────────────────────▼─────────────────────────────────┐
│               FastAPI  (integrations/openai_compat)            │
│                                                                 │
│  server.py ← app assembly only, no business logic              │
│  ├── *_routes.py  (17 个薄 Router 模块)                        │
│  ├── schemas.py   (DTO 中心)                                   │
│  └── legacy_exports.py  (旧测试兼容 re-export)                 │
└──────────────────────────────┬─────────────────────────────────┘
                               │ 内部调用
┌──────────────────────────────▼─────────────────────────────────┐
│                  Domain Layer  (src/mase/)                      │
│                                                                 │
│  cost_center · audit_log · auth_policy · privacy              │
│  lifecycle · quality_score · answer_support · refusal_quality  │
│  why_not_remembered · synthetic_replay · golden_tests         │
│  slo_dashboard · drift_detector · incidents · inspector_registry│
│  repair_cases · repair_diff · repair_sandbox · repair_execution│
│  trace_recorder · metrics · health_tracker · event_bus ...    │
└─────────────────────────────────────────────────────────────────┘
```

**设计原则**

- `server.py` 只负责 app 组装、中间件、路由 include，不堆业务逻辑
- 业务逻辑放 `src/mase/*.py` domain module（单文件 ≤ 300 行）
- API 适配放 `integrations/openai_compat/*_routes.py` 薄路由层
- DTO 集中在 `schemas.py`，前后端均通过类型约束
- Repair 执行必须经过 diff → sandbox → 人工审批 → 执行四步门控

---

## 功能模块

平台共 **22 个页面**，按功能分为四组：

### 总览 Overview

#### 01 · 运营 Cockpit（Dashboard）

系统全局仪表盘。

- **KPI 卡片**：事实总数、事件数、会话数、规则数、快照数
- **多维图表**：事实分类分布、事件角色分布、线程活跃度、时间轴活跃度、事实新鲜度、写入来源
- **系统地图**：各子系统（记忆写入、事件归档、召回、执行器、API 网关）的健康状态
- **快捷动作**：一键跳转到最常用的诊断页面
- **近期活动**：最新事实写入、事件记录摘要

#### 02 · Memory Observatory（观测台）

记忆系统的实时健康中心。

- **模型健康**：每个 provider/model 的成功次数、失败次数、EWMA 延迟、冷却状态、最近错误摘要
- **事件计数器**：write_fact、recall_hit、cache_hit、tool_call 等细粒度事件计数
- **平均延迟**：各操作的平均响应时间（ms）
- **Token 账本**：按 agent / model 汇总的 Token 消耗（含 Cost Center 快览）
- **API 健康**：auth_required、read_only、前端静态资源就绪状态

#### 03 · Cost Center（成本中心）

云端 API 成本的完整审计视图。

- **定价目录**：provider/model 的 input/output token 单价配置，支持生效时间
- **预算规则**：按 trace、日、agent 角色、provider/model 设置警戒线
- **成本汇总**：总花费、按 agent / 按 model 分组、最近高成本 trace
- **覆盖率报告**：已定价调用 vs 未定价调用 vs 本地免费调用；未定价模型清单
- **成本路由策略**：warn / enforce 两档策略，可审查每条路由的允许/阻断状态

---

### 可靠性 Reliability

#### 07 · Quality Score（质量评分）

对当前记忆集合给出综合质量评分（0–100），用于风险排序，不声称真实准确率。

- 按 scope / query 过滤
- 评分维度：新鲜度、事实完整性、证据密度、冲突风险
- 列出高风险事实项，供人工核查

#### 08 · Answer Support（答案支撑）

输入一段答案 + 查询，分析每个答案片段（Span）有没有记忆证据支撑。

- 分类：supported / weakly_supported / unsupported / stale_evidence
- 逐 Span 显示支撑来源和置信度
- 帮助判断"答案是不是在捏造"

#### 09 · Refusal Quality（拒答质量）

分析一条拒答，判断它是否合理。

- 四种分类：`appropriate_refusal`、`over_refusal`、`unsupported_answer`、`partially_supported_answer`
- 重点检测 **over_refusal**：有证据却拒答（高风险，用户体验差）
- 给出推荐处置动作

#### 10 · Why Not Remembered（为何未记住）

记忆链路断点诊断——当用户反馈"我告诉过你，你却忘了"时使用。

分五阶段逐步检测：

```
event_log → entity_extraction → fact_write → fact_recall → scope_match
```

每个阶段标注 OK / 异常，并给出样本数据和推荐动作。

#### 11 · Synthetic Replay（合成回放）

构造合成记忆场景，回放后用 `expected_terms` / `forbidden_terms` 验证答案质量。

- 完全只读，不写入真实记忆
- 批量运行多个 case，输出通过率
- 用于记忆系统的离线回归测试

#### 12 · Golden Tests（黄金测试）

核心回归门禁，确保关键记忆场景不退化。

- 支持 `severity: critical | high | medium`
- `release_gate` 字段：critical case 失败时输出 `BLOCKED`，阻断发布
- 按通过率和严重程度排序展示结果

#### 13 · SLO Dashboard（可靠性目标看板）

聚合所有可靠性信号，给出整体 SLO 状态。

- 汇总 golden pass rate、critical regression、contract health、成本覆盖率
- 每个 Objective 标注 `met / warning / breached`
- 整体状态：`healthy / degraded / critical`

#### 14 · Drift Detector（漂移检测）

检测记忆库中的三类漂移问题：

| 类型 | 说明 |
|------|------|
| `conflicting_fact_values` | 同一实体有互相矛盾的事实 |
| `duplicate_fact_value` | 重复记录，浪费召回空间 |
| `stale_memory_pressure` | 大量过时记忆未清理，影响召回质量 |

按严重程度（high / medium / low）排序，逐项展示受影响的事实。

---

### 运营 Operations

#### 04 · Audit Log（审计日志）

所有写入、删除、权限变更操作的不可篡改日志。

- 按 actor_id、action、resource_type、时间范围过滤
- 多租户隔离：每条日志携带 scope（tenant/workspace/visibility）
- 支持 CSV 导出

#### 05 · Privacy Guard（隐私防护）

扫描记忆库中的敏感信息（姓名、电话、邮箱、身份证、银行卡等）。

- 全库扫描：输出含敏感词的记忆条目清单
- 单条预览：展示脱敏前后对比
- 不自动修改，预览后由 Repair 或 Agent 执行

#### 06 · Lifecycle（生命周期）

事实的全生命周期可视化：`current → superseded → archived → expired`。

- TTL 管理：查看即将过期的记忆
- 契约检查：检测违反 category 契约的事实
- 分层视图：哪些事实处于哪个生命阶段

#### 15 · Incidents（事件中心）

将高风险的 Drift / SLO Breach 提升为可追踪 Incident。

- Incident 严重程度：`critical / high / medium / low`
- 状态流转：`open → acknowledged → resolved`
- 内置 Inspector 注册表：drift-detector、slo-dashboard、refusal-quality 等内置巡检器的状态总览

#### 16 · Repair Center（修复中心）

Agent 修复工单的完整执行闭环，**四步门控**确保安全。

```
1. 诊断 Diagnose  — 收集证据，生成结构化 diff 提案
2. Sandbox        — 只读沙箱验证，before/after 对比，不写入
3. 审批 Approve   — 人工确认，需 repair_approve 权限
4. 执行 Execute   — 白名单操作 + 全程 Audit Log
```

- 每个 Case 有独立 lifecycle（open → diagnosed → pending_approval → approved → executed → validated）
- 所有 Repair 操作写入 Audit Log，可追溯

---

### 记忆 Memory

#### 17 · Trace Studio（聊天 + 链路追踪）

最核心的调试入口：发起一次对话，实时查看完整执行链路。

- 支持 Thread / Scope / Model 参数
- Trace 步骤树：router → notetaker → fact_sheet → recall → executor → answer
- 每步显示：组件、输入/输出、延迟、Token 消耗、风险标记
- 历史 Trace 列表：按路由、成本、是否有云调用、是否有风险过滤

#### 18 · Recall Lab（召回实验室）

深入分析一次记忆召回过程。

- 输入 query + scope，查看所有召回命中
- 逐条解释命中原因（相似度、事实权重、新鲜度）
- 区分"当前事实"和"历史事件"来源
- Query 变体 + Top-K 敏感度测试

#### 19 · Fact Center（事实中心）

事实库的治理与历史视图。

- 字段：category / entity_key / entity_value / 新鲜度 / 来源 / 状态
- 历史链：查看一个事实被多少次更新/覆盖
- 冲突 & 重复提示
- 支持按 scope 过滤，读写模式下可安全编辑

#### 20 · Timeline Ops（时间线）

事件流水账的完整视图。

- 按 thread / role / scope 过滤
- 事件状态：`superseded / active / archived`
- 事件 → 事实 联动：查看一个事件最终产生了哪些事实
- 读写模式下支持纠错和快照生成

#### 21 · Session Vault（会话库）

短期上下文的全生命周期管理。

- Session 列表：TTL、过期状态、metadata、scope
- 安全清理预览：清理前展示影响范围
- 过期会话标注

#### 22 · Procedure Hub（规则中枢）

规则与工作流记忆的管理视图。

- 规则类型 / metadata / 版本历史 / 使用提示
- 版本化展示，支持按 updated_at 排序
- 读写模式下可安全增删

---

## 快速启动

### 方式一：双击启动器（推荐）

在 `E:\MASE-demo\` 目录下找到 `启动MASE.cmd`，双击运行，选择启动模式：

```
╔══════════════════════════════════════════════╗
║   MASE  Memory Reliability Platform          ║
║   记忆可靠性平台  · 正在启动...              ║
╚══════════════════════════════════════════════╝

[1] 默认端口 8765 启动
[2] 自定义端口启动
[3] 只读审计模式
```

启动后浏览器访问 `http://127.0.0.1:8765`。

### 方式二：PowerShell 脚本

```powershell
# 默认启动
.\scripts\start_platform.ps1

# 自定义端口
.\scripts\start_platform.ps1 -Port 8766

# 只读审计模式（禁用所有写入）
.\scripts\start_platform.ps1 -ReadOnly

# 环境变量方式
$env:MASE_PLATFORM_PORT = "8777"
.\scripts\start_platform.ps1
```

### 方式三：手动启动

```bash
# 1. 安装前端依赖
npm --prefix frontend install

# 2. 构建前端
npm --prefix frontend run build

# 3. 启动后端（自动 serve 前端静态文件）
cd E:\MASE-demo
python -m integrations.openai_compat.server
```

---

## 目录结构

```
E:\MASE-demo\
│
├── 启动MASE.cmd                    # 双击启动器（三模式菜单）
│
├── frontend/                       # React 前端
│   ├── src/
│   │   ├── App.tsx                 # 应用 Shell：导航、路由、顶栏、Scope
│   │   ├── i18n.ts                 # 中英文翻译表（zh / en 切换）
│   │   ├── api.ts                  # API Client（类型化请求）
│   │   ├── types.ts                # 全局 TypeScript 类型
│   │   ├── styles.css              # 全局深色视觉系统
│   │   ├── components/             # 共享组件
│   │   │   ├── Card.tsx
│   │   │   ├── DataTable.tsx
│   │   │   ├── JsonBlock.tsx
│   │   │   ├── RepairExecutionPanel.tsx
│   │   │   ├── ScopeBar.tsx        # Tenant / Workspace / Visibility 选择器
│   │   │   ├── ScopeGuard.tsx      # Scope 配置提示
│   │   │   └── StatCard.tsx
│   │   └── pages/                  # 22 个功能页面
│   └── index.html
│
├── integrations/openai_compat/     # FastAPI 层
│   ├── server.py                   # App assembly（只组装，不堆逻辑）
│   ├── schemas.py                  # DTO 中心
│   ├── legacy_exports.py           # 旧测试兼容 re-export
│   └── *_routes.py                 # 17 个薄 Router 模块
│
├── src/mase/                       # Domain 层（业务逻辑）
│   ├── cost_center.py
│   ├── audit_log.py
│   ├── auth_policy.py
│   ├── privacy.py
│   ├── lifecycle.py
│   ├── quality_score.py
│   ├── answer_support.py
│   ├── refusal_quality.py
│   ├── why_not_remembered.py
│   ├── synthetic_replay.py
│   ├── golden_tests.py
│   ├── slo_dashboard.py
│   ├── drift_detector.py
│   ├── incidents.py
│   ├── inspector_registry.py
│   ├── repair_cases.py / repair_diff.py / repair_sandbox.py / repair_execution.py
│   ├── trace_recorder.py
│   └── ... (50+ 模块)
│
├── scripts/
│   └── start_platform.ps1          # PowerShell 启动脚本
│
└── tests/                          # 481 个后端测试
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| 前端框架 | React 18 + TypeScript |
| 构建工具 | Vite |
| 样式 | 纯 CSS（无 UI 框架，深色设计系统） |
| 后端框架 | FastAPI（Python） |
| 运行时 | Uvicorn（ASGI） |
| 数据验证 | Pydantic v2 |
| 代码规范 | Ruff（Python）|
| 测试 | pytest（481 个后端测试） + Vitest（38 个前端测试） |

---

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MASE_PLATFORM_PORT` | `8765` | 后端监听端口 |
| `MASE_PLATFORM_HOST` | `127.0.0.1` | 后端绑定地址 |
| `MASE_READ_ONLY` | `""` | 设为 `1` 启用只读模式 |
| `MASE_INTERNAL_API_KEY` | `""` | 启用后，写入端点需要此 Key |

### 前端语言切换

- 首次访问：自动检测浏览器语言（`zh-*` → 中文，其他 → 英文）
- 切换方式：点击顶栏右侧的 **EN / 中** 胶囊按钮
- 持久化：选择保存在 `localStorage["mase_lang"]`，刷新后保持

### Scope 配置

每个页面的数据请求都会携带当前 Scope（`tenant_id / workspace_id / visibility`）。通过顶栏的 **Scope Bar** 切换。

- `visibility: private`：仅当前用户数据
- `visibility: shared`：当前 workspace 共享数据
- `visibility: global`：全租户数据（需要管理员权限）

---

## 安全与权限

### 读写模式

| 模式 | 说明 | 开启方式 |
|------|------|----------|
| 本地产品模式 | 全功能，含写入 | 默认 |
| 只读审计模式 | 所有写入、删除、纠错、快照由**后端**强制禁用 | `-ReadOnly` 或 `MASE_READ_ONLY=1` |

只读模式下，前端同样禁用所有写入按钮，顶部显示金色警告横幅。

### API Key 保护

当 `MASE_INTERNAL_API_KEY` 配置时：

- 写入端点（repair 执行、事实编辑、快照生成）需在 Header 携带 `Authorization: Bearer <key>`
- 前端通过侧边栏的 **Internal API Key** 输入框配置，保存在 `localStorage`

### 权限体系

Repair 执行需要 `repair_approve` 权限，审计日志记录每一次 Repair 操作的执行者、时间和 diff 内容。

### Audit Log 不可篡改性

所有治理操作写入 Audit Log，每条记录包含：
- `actor_id`、`action`、`resource_type`、`resource_id`
- 完整 `scope`（tenant / workspace / visibility）
- 时间戳、操作结果（success / failed）

---

## 常见问题

**Q：为什么可观测平台不提供直接修改记忆的界面？**

A：记忆的直接修改有较高的风险——改错了可能导致智能体产生错误的长期记忆。平台的设计理念是：**用 Repair Center 的四步门控工作流**（诊断 → Sandbox → 审批 → 执行）来修改，而不是提供"直接编辑"快捷键。这保证了每一次修改都有证据支撑、有沙箱验证、有人工确认、有 Audit Trail。

**Q：旧端口 8765 被占用怎么办？**

A：双击 `启动MASE.cmd` 选择 `[2] 自定义端口`，或者使用：
```powershell
.\scripts\start_platform.ps1 -Port 8766
```

**Q：Trace Studio 里看不到历史 Trace？**

A：历史 Trace 持久化需要 `trace_recorder` 写入权限。确认后端没有运行在只读模式（`MASE_READ_ONLY=1`），并且在 Trace Studio 中至少进行过一次对话。

**Q：Quality Score 准吗？**

A：Quality Score 是治理排序信号，帮助你发现哪些记忆条目**相对风险更高**，不代表绝对准确率。0–100 分仅供参考，请结合 Trace Studio 和 Recall Lab 的链路证据做最终判断。

**Q：Cost Center 里看到大量"未定价调用"？**

A：这通常是因为：(1) 使用了本地模型（Ollama 等，默认免费，不纳入计费）；(2) 使用了新的云端模型但尚未在定价目录中配置单价。进入 Cost Center → 定价目录，添加对应 provider/model 的 token 单价即可。

**Q：Golden Tests 显示 `BLOCKED`？**

A：有 `severity: critical` 的 case 失败时，Release Gate 输出 `BLOCKED`，表示当前记忆系统状态不满足发布标准。请进入 Why Not Remembered 或 Recall Lab 定位根因，再通过 Repair Center 修复后重跑测试。

---

## 回滚

平台使用 Git 管理版本，每个重要里程碑均有 commit。如需回滚 UI 优化：

```bash
# 查看提交历史
git log --oneline -10

# 回滚到指定 commit
git revert <commit-hash>
```

当前最新 checkpoint：

| Commit | 内容 |
|--------|------|
| `1f6d884e` | feat: 中英文切换 + 启动器 |
| `3947dccc` | feat: MASE 可观测平台 UI 重设计 |

---

*MASE Observatory — Built for memory reliability, not database administration.*
