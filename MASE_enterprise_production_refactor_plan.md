# MASE 企业生产级产品化改造计划

> 目标：把当前 MASE 从“强工程验证的 alpha-stage 白盒记忆引擎”升级为可在企业环境中长期运行、可审计、可扩展、可维护、可合规交付的 **Enterprise Memory Governance Platform**。
>
> 核心原则不变：**Govern memory first / Keep minimum necessary facts / Human-testable white-box / Only then inject into model context**。
>
> 本计划特别强调：代码边界清晰、模块可替换、数据可迁移、治理链路可追踪、企业安全可审计、后续开发者能读懂并维护代码。

---

## 0. 输入依据与当前状态判断

本文基于你提供的 `README(11).md` 最新版本整理。关键状态如下：

- MASE 当前定位是 **dual-whitebox memory engine for LLM agents**，目标是让 agent memory 在回灌模型上下文前可读、可编辑、可审计、可测试。
- 当前记忆层已分为三类：`Event Log`、`Entity Fact Sheet`、`Markdown / tri-vault`。
- 最新版本已引入 `src/mase/governance/`：Fact Contract、Evidence Span、Admission Gate、Conflict Resolver、Evidence Pack Compiler、Answer Claim Verifier。
- 多模态 ingestion 已具备 “read once, remember text” 链路：文件安全隔离、内容寻址、VLM/ASR 转写、文本 LLM 抽取事实、证据链回指原始字节。
- 当前质量门包括 pytest、ruff、mypy、compileall、repo hygiene、anti-overfit audit、frontend typecheck/test/build、git diff check。
- 当前 README 明确承认仍是 alpha-stage：语义泛化、大文档 claim memory、高并发 runtime、Review UI、Evidence Pack 默认注入、notetaker 到 governance tables 双写等仍需加强。

企业化判断：

MASE 的核心差异化不是“又一个 RAG/向量库”，而是 **事实治理内核**。企业生产级改造不应围绕“更大 top-k、更强 embedding、更复杂 agent chain”展开，而应围绕以下问题展开：

1. **谁写入了什么记忆？**
2. **这条记忆依据什么证据成立？**
3. **它在哪个租户、项目、用户、权限域内有效？**
4. **它是否过期、冲突、被撤销、被人工批准？**
5. **它为什么被召回？为什么被注入上下文？**
6. **模型最终回答中的每个事实是否能回指证据？**
7. **系统在高并发、故障、升级、迁移、审计、客户隔离、权限变更时是否仍然可靠？**

---

## 1. 产品化总目标

### 1.1 目标产品形态

建议把企业版 MASE 定义为：

> **MASE Enterprise：面向 AI Agent 与企业知识系统的白盒记忆治理平台。**

它不是单纯的“agent memory SDK”，而应成为一个可独立部署的 **Memory Governance Control Plane + Runtime Data Plane**。

### 1.2 企业客户关心的能力

| 企业诉求 | MASE 应提供的能力 |
|---|---|
| 准确率 | Fact Contract、Evidence Span、Claim Verifier、语义 claim verifier、评测回放 |
| 低幻觉 | Evidence Pack 默认链路、unsupported claim 拦截、unknown 显式返回 |
| 可审计 | append-only audit log、review actions、retrieval trace、answer trace |
| 权限隔离 | tenant/workspace/project/user namespace、RBAC/ABAC、row-level isolation |
| 合规 | PII/secret detection、retention policy、legal hold、export/delete、DLP hooks |
| 可维护 | 稳定 core、清晰接口、typed contracts、schema migrations、ADR、注释规范 |
| 可扩展 | plugin architecture、connectors、model providers、storage backends、retrievers |
| 高可用 | API/worker 解耦、queue、idempotency、backpressure、health checks、backup/restore |
| 可运营 | metrics、logs、traces、SLO dashboard、admin console |
| 可集成 | REST/OpenAPI、Python/TS SDK、MCP、LangChain、LlamaIndex、OpenAI-compatible API |

---

## 2. 顶层架构改造：从库到平台

### 2.1 当前架构的企业化问题

当前 MASE 已经有非常强的治理思想，但企业生产级会遇到以下结构性压力：

1. **SQLite + FTS5 适合本地、边缘、单机确定性运行，但不适合所有企业多租户高并发场景。**
2. **治理层虽已存在，但默认 runtime 仍部分依赖 legacy fact-sheet path。**
3. **Evidence Pack injection 是 opt-in，企业版应将它变成默认安全路径。**
4. **notetaker facts 没有完全双写 governance tables，长期会造成双轨事实不一致。**
5. **Review UI 尚未完成，企业客户无法高效处理 quarantine、conflict、merge、approve/reject。**
6. **缺少控制平面：租户、权限、策略、审计、密钥、配额、组织级配置。**
7. **缺少运行平面：异步任务、worker、队列、重试、幂等、backpressure、横向扩容。**

### 2.2 推荐目标架构

```text
┌────────────────────────────────────────────────────────────────────┐
│                         MASE Enterprise                            │
├────────────────────────────────────────────────────────────────────┤
│ Control Plane                                                      │
│  - Org / Tenant / Workspace / Project                              │
│  - Users / Groups / Service Accounts                               │
│  - RBAC / ABAC / Policy                                            │
│  - Review UI / Audit Explorer / Recall Inspector                   │
│  - Admin Console / Billing-Quota / Retention                       │
├────────────────────────────────────────────────────────────────────┤
│ API Plane                                                          │
│  - REST + OpenAPI                                                  │
│  - Python SDK / TypeScript SDK                                     │
│  - MCP Server                                                      │
│  - LangChain / LlamaIndex Adapters                                 │
│  - OpenAI-compatible Memory Endpoint                               │
├────────────────────────────────────────────────────────────────────┤
│ Runtime Plane                                                      │
│  - Ingestion API                                                   │
│  - Fact Governance Service                                         │
│  - Retrieval Orchestrator                                          │
│  - Evidence Pack Compiler                                          │
│  - Answer Claim Verifier                                           │
│  - Review Service                                                  │
│  - Async Workers + Job Queue                                       │
├────────────────────────────────────────────────────────────────────┤
│ Governance Plane                                                   │
│  - Fact Contract                                                   │
│  - Evidence Binder                                                 │
│  - Admission Gate                                                  │
│  - Conflict Resolver                                               │
│  - Policy Engine                                                   │
│  - Semantic Claim Verifier                                         │
│  - Retention / Legal Hold / Redaction                              │
├────────────────────────────────────────────────────────────────────┤
│ Data Plane                                                         │
│  - PostgreSQL: canonical facts, events, policies, reviews, audit   │
│  - Object Store: original files, transcripts, exports              │
│  - Search Index: FTS / OpenSearch / pg_trgm / optional vectors     │
│  - Cache: Redis / local cache                                      │
│  - Queue: NATS / Kafka / Redis Streams / cloud queue               │
├────────────────────────────────────────────────────────────────────┤
│ Observability & Reliability                                        │
│  - OpenTelemetry traces / metrics / logs                           │
│  - Health checks / readiness / liveness                            │
│  - Backup / restore / disaster recovery                            │
│  - Load tests / replay tests / eval harness                         │
└────────────────────────────────────────────────────────────────────┘
```

### 2.3 推荐部署形态

| 部署形态 | 目标用户 | 数据后端 | 说明 |
|---|---|---|---|
| Local SDK Mode | 开发者、本地 agent | SQLite + local files | 保留当前优势，便于 demo、测试、嵌入式场景 |
| Sidecar Mode | 单个 agent 服务 | SQLite 或 PostgreSQL | 作为 agent runtime 旁路服务运行 |
| Self-host Enterprise | 企业私有化 | PostgreSQL + object store + queue | 推荐主线，支持 SSO/RBAC/审计 |
| Cloud SaaS | 多租户平台 | 分区 PostgreSQL + managed infra | 后期形态，需最强租户隔离和合规能力 |
| Hybrid Gateway | 企业内网数据 | 本地 data plane + 云端 control plane | 适合数据不出域客户 |

---

## 3. 代码仓库结构改造

### 3.1 当前问题

企业化最怕三件事：

1. **业务逻辑散落在脚本、CLI、runtime、integration 中。**
2. **接口类型不稳定，后续无法安全重构。**
3. **实验代码和稳定代码混在一起，新开发者不知道什么能依赖、什么不能依赖。**

README 已提到 Stable Core、Compatibility Surface、Experimental Surface。企业版要把这个边界落实到代码目录、导入规则、CI 检查和文档中。

### 3.2 推荐目录结构

```text
src/mase/
  __init__.py

  contracts/                 # 纯数据契约：Pydantic/dataclass/TypedDict/Enums
    fact_contract.py
    evidence.py
    retrieval.py
    review.py
    tenancy.py
    errors.py

  core/                      # 稳定内核：不依赖 FastAPI、CLI、前端、具体模型供应商
    events.py
    facts.py
    clock.py
    ids.py
    state_machine.py
    invariants.py

  governance/                # 事实治理：Admission / Evidence / Conflict / Verification
    admission_gate.py
    evidence_binder.py
    conflict_resolver.py
    evidence_pack.py
    claim_verifier.py
    semantic_claim_verifier.py
    policy_engine.py

  retrieval/                 # 白盒召回：候选发现、打分、解释、编译
    candidate_sources.py
    query_expansion.py
    score_breakdown.py
    ranker.py
    compiler.py
    inspectors.py

  ingestion/                 # 文本、网页、文档、业务系统 ingestion
    pipeline.py
    chunker.py
    extractors.py
    connectors/
      base.py
      filesystem.py
      slack.py
      confluence.py
      notion.py
      github.py

  multimodal/                # 图片/PDF/音频转写与证据定位
    assets.py
    transcribers.py
    pdf.py
    audio.py
    images.py
    provenance.py

  storage/                   # 存储抽象与实现
    interfaces.py
    sqlite/
      repo.py
      migrations/
    postgres/
      repo.py
      migrations/
    object_store.py
    outbox.py

  api/                       # 企业 API：FastAPI / OpenAPI
    app.py
    deps.py
    routes/
      facts.py
      memories.py
      retrieval.py
      review.py
      audit.py
      tenants.py
    schemas.py

  workers/                   # 异步任务 worker
    app.py
    jobs.py
    ingestion_jobs.py
    verification_jobs.py
    retry.py

  authz/                     # 身份、权限、租户隔离
    principals.py
    rbac.py
    abac.py
    policy_context.py

  audit/                     # 审计事件与不可变日志
    events.py
    writer.py
    exporter.py

  observability/             # traces / metrics / logs
    tracing.py
    metrics.py
    logging.py
    health.py

  integrations/              # LangChain / LlamaIndex / MCP / OpenAI-compatible
    langchain.py
    llamaindex.py
    mcp_server.py
    openai_compat.py

  evals/                     # 评测、回放、golden cases
    harness.py
    datasets.py
    judges.py
    reports.py

  cli/                       # CLI 仅调用稳定 API，不承载核心逻辑
    main.py
    commands/

frontend/
  apps/admin-console/
  packages/ui/
  packages/api-client/

docs/
  adr/
  architecture/
  api/
  operations/
  governance/
  developer_guide/
```

### 3.3 导入依赖规则

必须强制执行单向依赖：

```text
contracts  <- core <- governance <- retrieval <- api / workers / integrations / cli
                         ^             ^
                         |             |
                     storage       ingestion / multimodal
```

规则：

- `contracts/` 不允许依赖任何 MASE 业务模块。
- `core/` 不允许依赖 FastAPI、CLI、具体数据库、具体模型 SDK。
- `governance/` 可以依赖 `contracts/`、`core/`、`storage.interfaces`，但不能直接依赖 PostgreSQL/SQLite 实现。
- `api/`、`workers/`、`cli/` 是边界层，只做编排，不写核心事实治理逻辑。
- `integrations/` 不允许绕过 governance service 直接写 facts。
- `experimental/` 代码必须加 feature flag，不能被 stable core import。

### 3.4 CI 中加入架构边界检查

新增脚本：

```bash
python scripts/audit_architecture_imports.py --strict
python scripts/audit_public_api_docstrings.py --strict
python scripts/audit_contract_versioning.py --strict
python scripts/audit_migration_safety.py --strict
```

示例规则：

```python
# scripts/audit_architecture_imports.py
# WHY: Enterprise maintainability depends on stable dependency direction.
# If API/worker concerns leak into core/governance, future refactors become risky.
FORBIDDEN_IMPORTS = {
    "mase.core": ["fastapi", "sqlalchemy", "requests", "mase.api", "mase.cli"],
    "mase.contracts": ["mase.governance", "mase.storage", "fastapi"],
    "mase.governance": ["mase.api", "mase.cli", "mase.integrations"],
}
```

---

## 4. 数据层改造：SQLite 本地优势 + PostgreSQL 企业主线

### 4.1 存储策略

保留 SQLite，但不要让 SQLite 承担所有企业场景。

| 场景 | 推荐后端 |
|---|---|
| 本地 demo / edge / single-user agent | SQLite + FTS5 |
| 企业生产 API | PostgreSQL |
| 大文档原始文件 | S3-compatible object store / MinIO / Azure Blob / GCS |
| 搜索候选发现 | PostgreSQL FTS + pg_trgm，必要时接 OpenSearch |
| embedding candidate discovery | pgvector / vector service，仅作为候选发现，不作为事实真相来源 |
| 异步任务 | NATS / Kafka / Redis Streams / managed queue |
| 缓存 | Redis，可替换 local cache |

### 4.2 Canonical Schema

企业版建议从一开始显式建模租户、权限域、来源、事实生命周期。

核心表：

```sql
-- Organizations own tenants. Keep org_id stable across billing, SSO, and audits.
CREATE TABLE organizations (
    org_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tenant is the hard isolation boundary for enterprise data.
CREATE TABLE tenants (
    tenant_id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(org_id),
    display_name TEXT NOT NULL,
    data_region TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Namespace scopes memory to a product, project, user, agent, or workflow.
CREATE TABLE memory_namespaces (
    namespace_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    namespace_type TEXT NOT NULL CHECK (namespace_type IN ('user','project','agent','team','system')),
    external_ref TEXT,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, namespace_type, external_ref)
);

-- Append-only event log. Do not mutate event payloads after insert.
CREATE TABLE memory_events (
    event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    namespace_id UUID NOT NULL REFERENCES memory_namespaces(namespace_id),
    actor_id UUID,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    event_time TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_json JSONB NOT NULL,
    payload_sha256 TEXT NOT NULL,
    idempotency_key TEXT,
    UNIQUE (tenant_id, idempotency_key)
);

-- Canonical governed facts.
CREATE TABLE facts (
    fact_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    namespace_id UUID NOT NULL REFERENCES memory_namespaces(namespace_id),
    contract_version TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_json JSONB NOT NULL,
    fact_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'candidate', 'quarantined', 'active', 'rejected',
        'superseded', 'expired', 'retracted', 'deleted'
    )),
    trust_level TEXT NOT NULL,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    ttl_expires_at TIMESTAMPTZ,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    active_version INTEGER NOT NULL DEFAULT 1
);

-- Evidence spans are mandatory before a fact can become active.
CREATE TABLE evidence_spans (
    evidence_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    fact_id UUID NOT NULL REFERENCES facts(fact_id),
    source_event_id UUID REFERENCES memory_events(event_id),
    source_document_id UUID,
    source_kind TEXT NOT NULL,
    byte_start BIGINT,
    byte_end BIGINT,
    char_start BIGINT,
    char_end BIGINT,
    page_number INTEGER,
    line_start INTEGER,
    line_end INTEGER,
    matched_text_sha256 TEXT NOT NULL,
    locator_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Explicit fact relationships. Never silently overwrite conflict history.
CREATE TABLE fact_edges (
    edge_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    from_fact_id UUID NOT NULL REFERENCES facts(fact_id),
    to_fact_id UUID NOT NULL REFERENCES facts(fact_id),
    edge_type TEXT NOT NULL CHECK (edge_type IN (
        'conflicts_with', 'supersedes', 'supports', 'duplicates', 'derived_from'
    )),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Human review workflow for quarantined/conflicting/high-risk facts.
CREATE TABLE review_tasks (
    review_task_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    namespace_id UUID NOT NULL REFERENCES memory_namespaces(namespace_id),
    target_type TEXT NOT NULL CHECK (target_type IN ('fact','evidence','answer','policy')),
    target_id UUID NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open','approved','rejected','merged','needs_info','closed')),
    priority TEXT NOT NULL DEFAULT 'normal',
    reason_code TEXT NOT NULL,
    assigned_to UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- Immutable audit events for compliance and debugging.
CREATE TABLE audit_events (
    audit_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    actor_id UUID,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    trace_id TEXT,
    before_json JSONB,
    after_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 4.3 必须加入数据库不变量

企业版不能只靠代码约定，必须把关键约束写入数据库、迁移脚本和测试：

1. `active fact` 必须至少有一个可验证 `evidence_span`。
2. `facts.status` 只能经由状态机转换，不允许随意 update。
3. 同一 `tenant_id + namespace_id + fact_key` 可以有多个历史事实，但同一时间只能有一个无冲突 active winner，除非 predicate 明确允许多值。
4. `memory_events` append-only，不允许业务 update/delete。
5. 所有跨租户查询必须带 `tenant_id`。
6. 任何 source document 删除前必须检查 legal hold、retention policy、active facts 引用。
7. 所有 destructive operation 必须写入 audit log。

### 4.4 Schema migration 规范

使用 Alembic 或等价迁移系统，建立以下规则：

- 迁移文件必须包含 `upgrade()` 和 `downgrade()`，如果不可逆必须写明理由。
- 大表变更采用 expand-migrate-contract：先加列，再回填，再切读写，再删除旧列。
- 所有迁移必须有 smoke test。
- 所有生产迁移必须支持 dry-run。
- 数据回填任务必须可断点续跑。
- 任何改变事实状态语义的迁移必须更新 `contract_version`。

```python
"""add fact retention policy columns

WHY:
    Enterprise customers need tenant-level retention and legal hold. These columns are
    additive and do not change existing fact admission semantics.

SAFETY:
    - Expand-only migration.
    - No existing rows are deleted.
    - Backfill is safe because NULL means "inherit tenant policy".
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("facts", sa.Column("retention_policy_id", sa.UUID(), nullable=True))
    op.add_column("facts", sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    # Safe because the columns are additive and do not own external resources.
    op.drop_column("facts", "legal_hold")
    op.drop_column("facts", "retention_policy_id")
```

---

## 5. 治理链路改造：让 governance 成为唯一长期事实写入路径

### 5.1 当前最重要的企业化改造点

README 明确提到：governance facts 已从 multimodal ingestion 和 `mase2_upsert_fact` facade 写入，但 conversational notetaker facts 尚未 dual-written into governance tables。

企业版必须完成以下切换：

```text
Legacy notetaker fact write
        |
        v
GovernedFactWriteFacade
        |
        v
Fact Candidate -> Admission Gate -> Evidence Binder -> Conflict Resolver
        |
        +--> active / quarantined / rejected / superseded
        |
        v
Evidence Pack eligible facts only
```

### 5.2 迁移策略：dual-write, shadow-read, cutover

| 阶段 | 写路径 | 读路径 | 目标 |
|---|---|---|---|
| Phase A | legacy + governance dual-write | legacy read | 收集差异，不影响现有行为 |
| Phase B | legacy + governance dual-write | shadow compare | 对比召回、answer、latency、conflict |
| Phase C | governance canonical write | governance read with fallback | 小流量灰度 |
| Phase D | governance canonical | governance read only | 企业默认路径 |
| Phase E | legacy read deprecated | migration/export only | 降低维护负担 |

### 5.3 状态机必须集中实现

不要让 API、worker、CLI 各自修改 `facts.status`。所有状态变更统一通过 `FactStateMachine`。

```python
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class FactStatus(StrEnum):
    """Lifecycle states for a governed fact.

    Invariant:
        A fact may only become ACTIVE after evidence binding and admission checks pass.
        Direct database updates that skip this state machine are production bugs.
    """

    CANDIDATE = "candidate"
    QUARANTINED = "quarantined"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    RETRACTED = "retracted"
    DELETED = "deleted"


@dataclass(frozen=True)
class FactTransition:
    """A validated state transition for audit and replay.

    WHY:
        Enterprise audits require not only the final state, but also who/what moved
        a fact through the lifecycle and which policy justified the transition.
    """

    fact_id: UUID
    from_status: FactStatus
    to_status: FactStatus
    reason_code: str
    actor_id: UUID | None
    request_id: str


class FactStateMachine:
    """Central authority for fact lifecycle transitions.

    Do not update `facts.status` outside this class.
    Tests must cover every allowed transition and every forbidden transition.
    """

    _ALLOWED: dict[FactStatus, set[FactStatus]] = {
        FactStatus.CANDIDATE: {FactStatus.ACTIVE, FactStatus.QUARANTINED, FactStatus.REJECTED},
        FactStatus.QUARANTINED: {FactStatus.ACTIVE, FactStatus.REJECTED},
        FactStatus.ACTIVE: {FactStatus.SUPERSEDED, FactStatus.EXPIRED, FactStatus.RETRACTED},
        FactStatus.SUPERSEDED: {FactStatus.RETRACTED},
        FactStatus.EXPIRED: {FactStatus.RETRACTED},
        FactStatus.REJECTED: set(),
        FactStatus.RETRACTED: set(),
        FactStatus.DELETED: set(),
    }

    def validate(self, transition: FactTransition) -> None:
        """Raise if the transition violates the governed fact lifecycle."""
        allowed_targets = self._ALLOWED[transition.from_status]
        if transition.to_status not in allowed_targets:
            raise InvalidFactTransition(
                f"Cannot move fact {transition.fact_id} from "
                f"{transition.from_status} to {transition.to_status}"
            )
```

### 5.4 Admission Gate 企业化

当前 Admission Gate 已覆盖 structurable、secret/PII、TTL 等。企业版要把它升级为可配置 policy engine。

新增能力：

- tenant-level policy：每个租户可定义哪些事实必须 review。
- namespace-level policy：项目、用户、团队记忆策略不同。
- data classification：public/internal/confidential/restricted。
- purpose binding：事实只能用于被授权目的，例如 support、sales、coding、research。
- retention rule：事实写入时绑定保留期限。
- consent rule：个人偏好、身份信息、健康/财务类信息默认 quarantine。
- risk score：Admission 不只返回 allow/deny，还返回可审计的 risk breakdown。

```python
@dataclass(frozen=True)
class AdmissionDecision:
    """Decision returned by the Admission Gate.

    Design note:
        This object is intentionally verbose. A boolean `allowed` value is not enough
        for enterprise review, audit, or customer-facing explanations.
    """

    outcome: Literal["allow", "quarantine", "reject"]
    reason_codes: tuple[str, ...]
    risk_score: float
    required_review_roles: tuple[str, ...]
    redacted_candidate: FactCandidate | None
```

### 5.5 Conflict Resolver 企业化

扩展 trust ladder：

| Trust level | 来源 | 默认行为 |
|---|---|---|
| E0 | 模型推断、无证据候选 | reject 或 quarantine |
| E1 | 低置信抽取 | quarantine |
| E2 | 文档证据 span 命中 | allow / review |
| E3 | 用户显式陈述 | allow，覆盖低级别 |
| E4 | 管理员/系统事实 | allow，需审计 |
| E5 | 法务/合规/安全策略 | allow，最高优先级 |

新增 resolver 输出：

```json
{
  "winner_fact_id": "...",
  "loser_fact_ids": ["..."],
  "edges": [
    {"type": "supersedes", "from": "new", "to": "old"},
    {"type": "conflicts_with", "from": "new", "to": "existing"}
  ],
  "requires_review": true,
  "reason": "new fact is E3 direct user statement; existing fact is E2 document extraction"
}
```

企业关键要求：**绝不允许低信任事实静默覆盖高信任事实。**

---

## 6. 召回与 Evidence Pack：从可选安全链路变成默认路径

### 6.1 目标

企业版默认回答链路应当是：

```text
User query
  -> Retrieve candidates
  -> Compile Evidence Pack
  -> Generate answer with pack constraints
  -> Verify answer claims
  -> return answer + evidence + warnings / refusal
```

不要让普通 runtime 继续绕过 Evidence Pack。legacy fact-sheet path 可以保留为兼容模式，但不应作为企业默认路径。

### 6.2 Evidence Pack 标准格式

```json
{
  "pack_id": "epk_...",
  "tenant_id": "...",
  "namespace_id": "...",
  "query": {
    "text": "What budget did I mention last time?",
    "time": "2026-07-04T00:00:00Z",
    "actor_id": "..."
  },
  "verified_facts": [
    {
      "fact_id": "...",
      "subject": "user",
      "predicate": "budget.preference",
      "object": {"amount": 5000, "currency": "USD"},
      "status": "active",
      "trust_level": "E3",
      "why_selected": "exact predicate match + recent direct user statement",
      "score_breakdown": {
        "keyword": 0.71,
        "structured_match": 1.0,
        "recency": 0.88,
        "trust": 0.95,
        "semantic": 0.42
      },
      "evidence": [
        {
          "source_type": "conversation",
          "source_ref": "event_...",
          "span": "...",
          "sha256": "..."
        }
      ]
    }
  ],
  "conflicts": [],
  "unknowns": [
    "No active fact found for exact purchase deadline."
  ],
  "do_not_assume": [
    "Do not infer budget from unrelated project facts."
  ],
  "policy_constraints": [
    "Do not expose PII unless explicitly requested by authorized actor."
  ]
}
```

### 6.3 召回策略：白盒语义，不回到黑盒向量库

企业版应补足“强同义词和语义泛化 recall”短板，但不能破坏白盒哲学。

推荐策略：

1. **Write-time tags**：写入事实时生成可检查 tags，例如 `budget`, `pricing`, `limit`, `spending_cap`。
2. **Read-time query expansion**：查询时使用可解释 synonym table + domain ontology。
3. **FTS / structured filters first**：优先使用结构化字段、predicate、namespace、time、trust level。
4. **Embedding 只做 candidate discovery**：embedding 结果必须进入 score breakdown，不能直接成为事实来源。
5. **LLM filter 必须输出 why_selected**：LLM 可参与 rerank，但必须给出可测试解释。
6. **召回结果必须能 replay**：query、candidate set、scores、pack、answer verifier 都要落库。

```python
class CandidateSource(Protocol):
    """Produces retrieval candidates with inspectable scoring.

    Invariant:
        A candidate source may discover facts, but it must never decide that a fact
        is true. Truth is determined by governance status and evidence, not by rank.
    """

    def search(self, query: RetrievalQuery) -> list[RetrievalCandidate]:
        ...
```

### 6.4 语义 Claim Verifier

当前 Claim Verifier 的已知短板是 substring/verbatim claim mapping。企业版必须加入语义 claim verifier：

```text
Answer sentence
  -> claim extraction
  -> canonical claim normalization
  -> entailment check against Evidence Pack
  -> contradiction check against conflicts / stale facts
  -> unsupported / supported / contradicted / unknown
```

建议分三层：

| 层级 | 方法 | 说明 |
|---|---|---|
| L1 | exact / substring | 当前能力，速度快、确定性强 |
| L2 | normalized claim match | 同义词、单位、日期、数字归一化 |
| L3 | entailment verifier | 小模型或强模型判断 support/contradict/unknown，必须保存 judge rationale |

验收指标：

- paraphrase claim detection recall > 85%。
- unsupported claim false negative rate < 3%。
- contradiction missed rate < 2%。
- verifier 失败时默认降级为 conservative refusal，而不是放行。

---

## 7. 多模态与大文档能力扩建

### 7.1 当前优势

当前多模态链路已经抓住了正确方向：**VLM/ASR 只做忠实转写，文本 LLM 再从 transcript 抽取 facts，并保留 byte-level provenance**。

企业版要在这个基础上增强大文档 claim memory。

### 7.2 大文档 Document Claim Memory

新增概念：

```text
Document Asset
  -> Page / Segment / Table / Figure / Audio Segment
  -> Transcript / OCR / Parsed Text
  -> Claim Candidate
  -> Governed Fact
  -> Evidence Span with page/line/byte locator
```

核心表：

```sql
CREATE TABLE source_documents (
    document_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    namespace_id UUID NOT NULL,
    object_uri TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE document_segments (
    segment_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL REFERENCES source_documents(document_id),
    segment_type TEXT NOT NULL CHECK (segment_type IN ('page','paragraph','table','figure','audio_segment')),
    page_number INTEGER,
    line_start INTEGER,
    line_end INTEGER,
    char_start BIGINT,
    char_end BIGINT,
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'
);
```

### 7.3 表格、图像、音频的事实抽取策略

| 类型 | 处理方式 | 证据定位 |
|---|---|---|
| PDF 文本 | parser + page map | page/line/char |
| 扫描 PDF | OCR/VLM transcript | page/box/char |
| 表格 | table extraction + cell map | row/column/cell span |
| 图片 | VLM caption + region locator | image sha256 + bounding box |
| 音频 | ASR + timestamp segments | start_ms/end_ms |
| 视频 | frame transcript + ASR | timestamp + frame hash |

企业版要避免“摘要即事实”的错误。摘要可以作为辅助，但 active fact 必须绑定可定位证据。

---

## 8. 企业 API 与 SDK

### 8.1 API 设计原则

- Contract-first：先定义 OpenAPI/JSON Schema，再实现。
- 所有 mutation API 支持 `Idempotency-Key`。
- 所有 API 返回 `request_id` 与 `trace_id`。
- 所有 fact/retrieval/answer API 都支持 `explain=true`。
- API 错误必须结构化，不返回任意字符串。
- API 版本显式放在路径或 header：`/v1/...`。

### 8.2 核心 API

```http
POST /v1/memory-events
POST /v1/facts:candidate
POST /v1/facts:upsert-governed
GET  /v1/facts/{fact_id}
GET  /v1/facts?namespace_id=...&status=active
POST /v1/retrieval:evidence-pack
POST /v1/answers:verify
GET  /v1/review-tasks
POST /v1/review-tasks/{id}:approve
POST /v1/review-tasks/{id}:reject
POST /v1/review-tasks/{id}:merge
GET  /v1/audit-events
GET  /v1/recall-traces/{trace_id}
```

### 8.3 SDK 设计

Python SDK：

```python
from mase_client import MaseClient

client = MaseClient(
    base_url="https://mase.example.com",
    api_key="...",
    tenant_id="tenant_123",
)

pack = client.retrieval.create_evidence_pack(
    namespace_id="project_abc",
    query="What deployment target did the user approve?",
    explain=True,
)

verification = client.answers.verify(
    evidence_pack_id=pack.pack_id,
    answer="The deployment target is us-east-1.",
)
```

SDK 必须内置：

- retry with backoff。
- idempotency key helper。
- typed response models。
- trace_id exposure。
- local dev mode。
- API compatibility check。

### 8.4 MCP 企业化

MCP tools 不应直接开放危险写操作。推荐拆分：

| MCP capability | 默认权限 | 说明 |
|---|---|---|
| `mase.search_memory` | read | 返回 Evidence Pack，不返回裸 chunk |
| `mase.explain_recall` | read | 展示 why_selected、score breakdown |
| `mase.propose_fact` | write candidate | 只能创建 candidate，不能直接 active |
| `mase.review_fact` | privileged | 需要人工/管理员权限 |
| `mase.retract_fact` | privileged | 必须写 audit log |

---

## 9. Review UI / Admin Console

### 9.1 为什么 Review UI 是企业版 P0

README 里已经有 governance data model，但 UI 尚未建成。企业客户不可能只靠 CLI 或 SQL 管理 quarantine/conflict/review。Review UI 是把“白盒设计”变成可运营产品的关键。

### 9.2 必做页面

| 页面 | 功能 |
|---|---|
| Review Inbox | 查看 quarantined facts、PII、conflicts、low evidence、policy violations |
| Fact Detail | subject/predicate/object、状态、trust、证据、历史版本、边 |
| Evidence Viewer | 原文 span 高亮、PDF 页码、音频时间戳、图片区域 |
| Conflict Resolver | 并排比较新旧事实、trust ladder、选择 active winner |
| Recall Inspector | 查询、候选、score breakdown、why_selected、Evidence Pack |
| Answer Verifier | 句子级 supported/unsupported/contradicted 标注 |
| Audit Explorer | 谁在什么时候写入、批准、拒绝、撤销、导出 |
| Policy Builder | 租户级/namespace 级 admission、retention、review 策略 |
| Tenant Admin | 用户、组、service account、API key、SSO、配额 |

### 9.3 UI 设计原则

- 永远展示证据，不只展示结论。
- 所有 approve/reject/merge 都必须要求 reason。
- 高风险事实默认不可批量 approve。
- 审计事件可导出。
- Recall Inspector 必须可复制为 bug report。
- 用户能看到 “why this memory was used”。

---

## 10. 高并发与运行时硬化

### 10.1 生产级 runtime 原则

当前 README 已将 server-grade async/runtime hardening 列为 roadmap。企业版需要把 runtime 当作独立产品能力。

核心原则：

1. API request 不做长耗时 ingestion。
2. 文件、多模态、LLM 抽取、verification 全部异步 job 化。
3. 所有 job 支持幂等、重试、死信队列。
4. 写路径使用事务 + outbox pattern。
5. 召回路径支持超时、降级、缓存。
6. 每个租户有配额和限流。
7. worker 可横向扩容。

### 10.2 Job 模型

```python
@dataclass(frozen=True)
class IngestionJob:
    """A durable asynchronous ingestion request.

    Invariant:
        Jobs must be idempotent. Retrying the same job may create new audit events,
        but must not duplicate canonical facts or source documents.
    """

    job_id: UUID
    tenant_id: UUID
    namespace_id: UUID
    source_uri: str
    idempotency_key: str
    requested_by: UUID
```

### 10.3 Outbox pattern

事务内写入事实和 outbox：

```text
BEGIN
  insert memory_event
  insert candidate facts
  insert audit_event
  insert outbox_event('fact.candidate.created')
COMMIT

worker reads outbox -> publishes to queue -> marks sent
```

这样可以避免“数据库写成功但队列消息丢失”的生产事故。

### 10.4 幂等与并发控制

- 所有写 API 要求 `Idempotency-Key`。
- fact upsert 使用 `fact_key + namespace_id + tenant_id` 做冲突检测。
- active winner 使用 optimistic lock，例如 `active_version`。
- 并发 review 必须检测版本冲突。
- document ingestion 用 `sha256 + namespace_id` 去重。
- worker retry 必须能识别已完成步骤。

### 10.5 SLO 建议

| 能力 | 初始 SLO |
|---|---|
| Active fact lookup | p95 < 100ms |
| Evidence Pack compile | p95 < 800ms for small namespaces |
| Answer verification | p95 < 2s without LLM verifier；p95 < 8s with semantic verifier |
| API availability | 99.9% self-host baseline |
| Ingestion durability | committed event loss = 0 |
| Cross-tenant leak | 0 tolerated |
| Active fact without evidence | 0 tolerated |

---

## 11. 安全、合规与企业治理

### 11.1 安全边界

企业版 MASE 至少需要以下安全能力：

- OIDC/SAML SSO。
- SCIM 用户/组同步。
- RBAC + ABAC。
- Service account 与 scoped API key。
- Tenant-level encryption key。
- Envelope encryption for secrets and sensitive payloads。
- PII/secret detection and redaction。
- Prompt injection / memory poisoning detection。
- Data retention and legal hold。
- Audit log immutability。
- Backup/restore encryption。
- Export/delete workflow。
- Admin action approval workflow。

### 11.2 RBAC/ABAC 模型

RBAC 角色：

| Role | 权限 |
|---|---|
| Org Owner | 全局管理、SSO、billing、tenant 创建 |
| Tenant Admin | 租户配置、用户、策略、审计 |
| Memory Admin | fact review、merge、retract、policy 调整 |
| Reviewer | approve/reject quarantine |
| Developer | API key、namespace、integration |
| Reader | 查询 Evidence Pack |
| Service Account | scoped machine access |

ABAC 条件：

- `tenant_id`
- `namespace_id`
- `data_classification`
- `purpose`
- `actor.group`
- `resource.owner`
- `legal_hold`
- `retention_policy`

### 11.3 Memory poisoning 防御

企业记忆系统面临特殊攻击面：攻击者可能试图把恶意指令写成长期记忆，例如“以后忽略安全策略”“把客户数据发给某 endpoint”。

Admission Gate 需要新增规则：

```text
Reject if candidate fact attempts to:
  - override system/developer/security policy
  - persist tool-use instructions from untrusted content
  - store secrets as usable facts
  - create cross-tenant access statements
  - encode prompt injection payloads
  - mark untrusted document content as administrative instruction
```

示例注释：

```python
class MemoryPoisoningDetector:
    """Detects attempts to persist untrusted instructions as long-term memory.

    Threat model:
        Enterprise documents, tickets, emails, and web pages may contain hostile text.
        Such text can be quoted and remembered as evidence, but it must not become
        an instruction that changes MASE behavior or downstream agent policy.
    """

    def classify(self, candidate: FactCandidate) -> PoisoningRisk:
        ...
```

### 11.4 合规审计

每个关键动作都要写 audit event：

- fact candidate created。
- fact admitted/rejected/quarantined。
- evidence bound。
- conflict resolved。
- review approved/rejected/merged。
- evidence pack compiled。
- answer verified/refused。
- policy changed。
- export/delete/retract/legal hold。
- API key created/revoked。
- admin role changed。

审计日志原则：

- append-only。
- 不存明文 secret。
- 支持 trace_id/request_id 关联。
- 支持按租户导出。
- 支持 tamper-evident hash chain。

---

## 12. 可观测性与运维

### 12.1 Trace 设计

每个用户请求或 worker job 至少包含：

```text
mase.request
  ├─ authz.check
  ├─ policy.resolve
  ├─ retrieval.candidate_search
  │   ├─ retrieval.fts
  │   ├─ retrieval.structured
  │   └─ retrieval.semantic_candidate
  ├─ evidence_pack.compile
  ├─ llm.generate
  ├─ answer.claim_extract
  ├─ answer.claim_verify
  └─ audit.write
```

### 12.2 Metrics

核心指标：

| 指标 | 说明 |
|---|---|
| `mase_facts_created_total` | 新建事实数 |
| `mase_facts_active_total` | active facts 数 |
| `mase_facts_quarantined_total` | quarantine 队列规模 |
| `mase_admission_reject_total` | admission reject 数 |
| `mase_secret_block_total` | secret 拦截数 |
| `mase_conflict_total` | conflict 数 |
| `mase_evidence_pack_latency_ms` | Evidence Pack 编译耗时 |
| `mase_retrieval_candidate_count` | 候选数量 |
| `mase_answer_unsupported_claim_total` | unsupported claim 数 |
| `mase_answer_refuse_total` | verifier refuse 数 |
| `mase_cross_tenant_violation_total` | 必须永远为 0 |

### 12.3 日志规范

- JSON structured logging。
- 每条 log 包含 `tenant_id_hash`，不要直接输出敏感 tenant/customer name。
- 每条 log 包含 `request_id`、`trace_id`。
- 不记录 raw prompt、secret、PII，除非进入受控 debug mode。
- debug mode 有时间限制、权限限制、审计记录。

---

## 13. 测试、评测与质量门

### 13.1 测试金字塔

| 层级 | 内容 |
|---|---|
| Unit tests | state machine、admission、evidence binding、conflict resolver |
| Property tests | active fact 必有 evidence；低信任不能覆盖高信任；跨租户不可见 |
| Contract tests | REST/OpenAPI、SDK、MCP schema 稳定性 |
| Migration tests | 每个 migration 可在真实数据快照上升级/降级或安全失败 |
| Integration tests | API + DB + queue + worker + object store |
| E2E tests | ingestion -> governance -> retrieval -> answer verify -> review |
| Load tests | 并发写入、并发召回、大租户 namespace、worker backlog |
| Security tests | prompt injection、secret leakage、tenant isolation、authz bypass |
| Replay tests | 旧 run artifacts 和 benchmark examples 重放 |
| Eval tests | LongMemEval / NoLiMa / LV-Eval / synthetic governance cases |

### 13.2 新增企业质量门

```bash
# Existing gates remain.
python -m pytest -q
python -m ruff check .
python -m mypy
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build

# Enterprise gates.
python scripts/audit_architecture_imports.py --strict
python scripts/audit_public_api_docstrings.py --strict
python scripts/audit_contract_versioning.py --strict
python scripts/audit_migration_safety.py --strict
python scripts/audit_tenant_isolation.py --strict
python scripts/audit_no_raw_secret_logs.py --strict
python scripts/run_governance_invariant_tests.py --strict
python scripts/run_replay_regression.py --suite enterprise_smoke
python scripts/run_load_smoke.py --profile ci
```

### 13.3 必须长期追踪的评测指标

| 指标 | 目标 |
|---|---|
| active fact evidence coverage | 100% |
| unsupported claim rate | 持续下降，企业默认 < 1-3% |
| stale fact injection rate | 0 或接近 0 |
| conflict silent rate | 0 |
| cross-tenant leakage | 0 |
| secret persisted active | 0 |
| PII quarantine recall | > 95% |
| semantic paraphrase claim detection | > 85% 初始目标 |
| migration failure recovery | 100% 可恢复 |
| replay determinism | 关键治理 case 结果稳定 |

---

## 14. 代码注释与文档规范

### 14.1 注释哲学

企业生产级代码的注释不是解释语法，而是解释：

1. **Why**：为什么这样设计。
2. **Invariant**：必须永远成立的不变量。
3. **Threat model**：这里防御什么攻击或失败模式。
4. **Boundary**：这个模块能依赖什么、不能依赖什么。
5. **Failure behavior**：失败时应如何降级。
6. **Migration safety**：数据结构变化对旧数据意味着什么。
7. **Audit semantics**：什么动作必须记录。
8. **Concurrency semantics**：是否幂等、是否可重试、是否需要锁。

不要写低价值注释：

```python
# BAD: increment i by 1
for i in range(n):
    ...
```

要写高价值注释：

```python
# GOOD:
# We deliberately reject unsupported claims here instead of returning a best-effort
# answer. In enterprise mode, a conservative unknown is safer than an unverifiable fact.
if verifier_result.has_unsupported_claims:
    return Refusal.with_unknowns(verifier_result.unknowns)
```

### 14.2 Public API docstring 模板

```python
def compile_evidence_pack(query: RetrievalQuery, *, policy: RetrievalPolicy) -> EvidencePack:
    """Compile governed memory into a replayable context bundle.

    The Evidence Pack is the only enterprise-supported input format for model
    context injection. It contains verified facts, conflicts, unknowns, policy
    constraints, and recall explanations.

    Invariants:
        - Only ACTIVE facts with bound evidence may appear in `verified_facts`.
        - QUARANTINED or REJECTED facts may appear only under `conflicts` or
          `warnings`, never as verified facts.
        - Every selected fact must include `why_selected` and `score_breakdown`.

    Args:
        query: Tenant-scoped retrieval request.
        policy: Runtime policy controlling trust thresholds, time windows, and
            whether semantic candidate discovery is allowed.

    Returns:
        A replayable EvidencePack suitable for answer generation and verification.

    Raises:
        TenantIsolationError: If query.namespace_id does not belong to query.tenant_id.
        PolicyViolationError: If the actor is not allowed to retrieve this namespace.
    """
```

### 14.3 类注释模板

```python
class ConflictResolver:
    """Resolves governed fact conflicts without silent overwrites.

    Design principle:
        MASE does not use "last write wins" for long-lived facts. A newer claim can
        supersede an older one only when trust, scope, validity time, and policy allow it.

    Enterprise audit requirement:
        Every conflict decision must emit fact_edges and audit_events so that an
        operator can reconstruct why the active fact changed.
    """
```

### 14.4 危险函数必须写注释

以下函数必须有 docstring + inline comments：

- 改变 fact 状态的函数。
- 删除、撤销、导出数据的函数。
- 跨租户查询相关函数。
- evidence span binding 函数。
- secret/PII redaction 函数。
- LLM verifier 降级逻辑。
- migration/backfill。
- retry/idempotency 逻辑。
- prompt construction / Evidence Pack injection。

### 14.5 注释审查清单

PR review 必问：

- 这个模块的核心 invariant 是否写清楚？
- 失败/降级行为是否写清楚？
- 是否解释了为什么不用更简单的方案？
- 是否说明了并发和幂等语义？
- 是否说明了安全边界？
- public API 是否有 docstring？
- 是否有 ADR 记录架构取舍？

### 14.6 ADR 规范

每个重大决策写 `docs/adr/YYYY-MM-DD-title.md`：

```markdown
# ADR: Make Evidence Pack the default enterprise injection path

## Status
Accepted

## Context
The legacy fact-sheet path can bypass governance metadata and answer verification.
Enterprise customers require auditable, evidence-backed context injection.

## Decision
In enterprise mode, all model context injection must go through Evidence Pack.
Legacy fact-sheet injection remains behind a compatibility flag.

## Consequences
- More latency per answer.
- Better auditability and lower hallucination risk.
- Requires default verifier and fallback behavior.
```

---

## 15. Plugin / Extension 体系

### 15.1 为什么需要 plugin architecture

企业客户的数据源、模型供应商、合规策略、搜索后端都不同。如果没有清晰 plugin interface，代码会快速变成一堆 if/else。

### 15.2 稳定扩展点

```python
class ModelProvider(Protocol): ...
class EmbeddingProvider(Protocol): ...
class Transcriber(Protocol): ...
class FactExtractor(Protocol): ...
class CandidateSource(Protocol): ...
class Ranker(Protocol): ...
class EvidenceBinder(Protocol): ...
class AdmissionPolicy(Protocol): ...
class StorageRepository(Protocol): ...
class ObjectStore(Protocol): ...
class AuditSink(Protocol): ...
class Connector(Protocol): ...
```

### 15.3 Plugin 规则

- plugin 不允许直接写 canonical tables，必须通过 service/facade。
- plugin 输出必须符合 contracts。
- plugin 必须声明 capability、version、trust boundary。
- plugin 必须有 integration tests。
- plugin 失败不能破坏 core transaction。
- plugin 不能绕过 tenant isolation。

---

## 16. Release Engineering 与供应链安全

### 16.1 版本策略

- `MASE Core` 使用 SemVer。
- `contracts` 单独 version。
- API 使用 `/v1`、`/v2`。
- 数据库 schema 使用 migration version。
- Evidence Pack 使用 `pack_schema_version`。
- Fact Contract 使用 `contract_version`。

### 16.2 发布流程

```text
PR
  -> lint/typecheck/unit tests
  -> architecture audits
  -> contract compatibility tests
  -> migration tests
  -> security scans
  -> integration tests
  -> replay regression
  -> build container
  -> generate SBOM/provenance
  -> sign artifact
  -> staging deploy
  -> smoke/load tests
  -> canary
  -> production rollout
```

### 16.3 供应链安全

企业版建议加入：

- lockfile 固定依赖。
- SBOM 生成。
- container image signing。
- release provenance。
- dependency vulnerability scan。
- secret scan。
- reproducible build 尽量推进。

---

## 17. 分阶段路线图

### Phase 0：稳定边界与治理默认路线

目标：让企业化改造不破坏现有 benchmark 和用户路径。

任务：

- 明确 stable core / compatibility / experimental 目录边界。
- 新增架构导入检查。
- 将 governance contracts 移到 `contracts/`。
- 所有 public API 补 docstring。
- 所有危险路径补注释。
- 给 Evidence Pack injection 增加 enterprise default feature flag。
- 建立 ADR 目录。

验收：

- 现有测试全部通过。
- 架构导入检查通过。
- public API docstring coverage > 90%。
- `MASE_ENTERPRISE_MODE=1` 时 Evidence Pack 是默认注入路径。

### Phase 1：notetaker facts 双写 governance tables

目标：消除 legacy fact sheet 与 governance tables 的长期分裂。

任务：

- 实现 `GovernedFactWriteFacade`。
- notetaker 输出统一转 FactCandidate。
- legacy + governance dual-write。
- shadow-read 对比。
- 差异报告。

验收：

- 100% notetaker facts 有 candidate 记录。
- active facts 均有 evidence span。
- dual-write 差异可解释。
- 低信任覆盖高信任 case 全部被拒绝或 quarantine。

### Phase 2：PostgreSQL 企业存储后端

目标：支持多租户、高并发、横向扩展基础。

任务：

- storage interfaces 完成。
- PostgreSQL repo 实现。
- Alembic migrations。
- tenant isolation tests。
- outbox table。
- object store interface。

验收：

- SQLite 与 PostgreSQL 合约测试一致。
- 所有查询带 tenant scope。
- active fact without evidence = 0。
- migration smoke test 通过。

### Phase 3：Review UI 与 Audit Explorer

目标：让白盒治理可被企业运营。

任务：

- Review Inbox。
- Fact Detail。
- Evidence Viewer。
- Conflict Resolver。
- Audit Explorer。
- Recall Inspector MVP。

验收：

- quarantine fact 可在 UI approve/reject。
- conflict 可在 UI merge/supersede。
- 每个 review action 产生 audit event。
- Evidence Span 可高亮展示。

### Phase 4：异步 ingestion 与 runtime hardening

目标：生产服务稳定性。

任务：

- queue + worker。
- idempotent jobs。
- retry/dead letter。
- rate limit。
- health/readiness/liveness。
- OpenTelemetry instrumentation。
- load test。

验收：

- worker crash 后 job 可恢复。
- 重复请求不产生重复 facts。
- p95 evidence pack latency 达标。
- observability dashboard 可定位慢请求。

### Phase 5：白盒语义召回与语义 Claim Verifier

目标：补足 synonym/generalization 与 paraphrase claim mapping 短板。

任务：

- write-time tags。
- read-time query expansion。
- semantic candidate source。
- score breakdown 标准化。
- L2 normalized claim match。
- L3 entailment verifier。

验收：

- paraphrased answer claims 可检测。
- embedding candidate 不可绕过 evidence。
- every selected fact has why_selected。
- hallucination eval 指标下降。

### Phase 6：企业安全、合规、SaaS readiness

目标：支持真实企业交付。

任务：

- OIDC/SAML。
- RBAC/ABAC。
- scoped API keys。
- retention/legal hold。
- export/delete。
- encryption/KMS。
- SBOM/provenance/signing。
- backup/restore。

验收：

- cross-tenant leak tests = 0 failures。
- audit export 可用于客户审计。
- restore drill 通过。
- security review 通过。

---

## 18. P0 优先级清单

建议马上做的 12 件事：

1. 建立 `contracts/`，把 Fact/Evidence/Pack/Review/Tenant 合约稳定下来。
2. 建立 `GovernedFactWriteFacade`，notetaker facts 进入 governance dual-write。
3. 将 Evidence Pack 设为 enterprise mode 默认注入路径。
4. 增加 FactStateMachine，禁止散落更新 `facts.status`。
5. 增加 tenant/namespace 数据模型，即使先在 SQLite 中模拟。
6. 抽象 `StorageRepository`，准备 PostgreSQL 后端。
7. 增加 `audit_events`，所有治理动作落审计。
8. 增加 architecture import audit。
9. 增加 public API/docstring audit。
10. 实现 Review Inbox MVP。
11. 实现 Recall Inspector MVP。
12. 实现 semantic claim verifier PoC，先覆盖 paraphrase 支持/矛盾/未知。

---

## 19. 关键风险与规避

| 风险 | 表现 | 规避 |
|---|---|---|
| 过度平台化 | 功能庞杂，核心变慢 | stable core 保持小而硬；enterprise 能力通过边界层扩展 |
| 向量库黑盒化回潮 | embedding top-k 直接进上下文 | embedding 只做 candidate discovery，必须 Evidence Pack + score breakdown |
| legacy/governance 双轨分裂 | 两套事实不一致 | dual-write -> shadow-read -> cutover，有明确废弃计划 |
| UI 先行但治理不稳 | 漂亮但不可审计 | Review UI 只消费 canonical governance tables |
| 高并发破坏事实一致性 | 冲突覆盖、重复 facts | idempotency、state machine、optimistic lock、outbox |
| 评测过拟合 | benchmark 高但真实差 | anti-overfit audit、真实客户 replay、synthetic adversarial cases |
| 注释不足 | 新成员不敢改 | docstring audit、ADR、危险函数注释强制 |
| 企业安全遗漏 | 跨租户、secret、PII 泄露 | tenant isolation tests、DLP、audit、RBAC/ABAC |

---

## 20. 最终产品验收标准

MASE Enterprise 可宣称“生产级”前，建议至少满足：

1. **所有 active facts 100% 有可验证 evidence span。**
2. **所有长期事实写入统一通过 governance path。**
3. **Evidence Pack 是企业默认上下文注入格式。**
4. **Answer Claim Verifier 是默认回答后处理链路。**
5. **Review UI 可处理 quarantine/conflict/merge/retract。**
6. **PostgreSQL 后端通过与 SQLite 相同的合约测试。**
7. **跨租户隔离测试覆盖 API、storage、worker、search、audit。**
8. **所有 mutation API 支持 idempotency。**
9. **所有关键治理动作写入 audit log。**
10. **OpenTelemetry traces/metrics/logs 覆盖核心链路。**
11. **CI 包含 architecture、contract、migration、tenant isolation、安全扫描。**
12. **public API docstring coverage > 90%，危险函数注释覆盖 100%。**
13. **有 ADR 记录 Evidence Pack 默认化、PostgreSQL 后端、plugin architecture、tenant isolation 等重大决策。**
14. **有 backup/restore 演练记录。**
15. **有 replay regression suite，能复现关键 benchmark 与真实失败案例。**

---

## 21. 推荐外部标准参考

- OpenTelemetry：traces / metrics / logs / collector / instrumentation。
- OWASP Top 10 for LLM Applications：prompt injection、training/data poisoning、model DoS、supply-chain、output handling、excessive agency 等风险。
- NIST AI Risk Management Framework：govern / map / measure / manage 的 AI 风险治理思路。
- SLSA：软件供应链完整性、build provenance、artifact integrity。
- OpenAPI：API contract-first 与 SDK 生成。

---

## 22. 一句话路线

MASE 企业化不应走“把 SQLite 换成云数据库、把 CLI 包成 API”的浅层路线，而应走：

> **事实治理内核稳定化 → governance 默认写读路径 → 多租户与审计 → Review UI → 异步高并发运行时 → 白盒语义召回与语义验证 → 企业安全合规交付。**

只要坚持这个顺序，MASE 的白盒哲学不会被平台化冲淡，反而会成为企业级产品的护城河。 🧭

---

## 23. 2026-07-04 本地实施状态

状态：已完成企业化 **Phase 0** 和 **Phase 1** 的本地可验证实现，并落地一组 Phase 3/4/5/6 的最小原语；尚未完成真实 PostgreSQL、SSO、SaaS、队列和企业基础设施验收。

已完成：

- **Phase 0 稳定边界**：新增 `src/mase/contracts/`、`src/mase/core/`、`src/mase/storage/`；FactContract 迁入 contracts 并保留 governance 兼容 re-export；新增 `FactStateMachine`、`StorageRepository` 协议、architecture import audit、public API docstring audit 与 ADR。
- **Phase 1 notetaker governance 双写**：新增 `GovernedFactWriteFacade`；`MASE_ENTERPRISE_MODE=1` 或 `MASE_GOVERNANCE_DUAL_WRITE=1` 时，legacy `mase2_upsert_fact` 会记录 governance candidate 并提议 governed fact；无可定位来源时 quarantine，不进入 active；提供 shadow-read diff。
- **企业默认 Evidence Pack 安全路径**：`MASE_ENTERPRISE_MODE=1` 默认启用 Evidence Pack injection，显式 `MASE_EVIDENCE_PACK_INJECTION=0` 可关闭。
- **Review/Admin MVP**：Facts 页面接入 Review Inbox，支持 approve/reject/retract/edit/merge/export；API 侧所有 review 写动作要求写权限并落 audit。
- **大文档/服务硬化/评测最小闭环**：document claims、幂等/限流/backup/restore/trace、governance eval CLI、L2 deterministic semantic claim verifier 已具备测试覆盖。

本地验收证据：

- `python -m pytest -m "not integration and not slow" -q` → 844 passed, 2 warnings。
- `python -m ruff check .`、`python -m mypy`、`python scripts/audit_architecture_imports.py --strict`、`python scripts/audit_public_api_docstrings.py --strict` 全部通过。
- `npm --prefix frontend test -- src/api.test.ts` → 26 passed；`npm --prefix frontend run build` 通过。
- `python scripts/run_governance_eval.py --out-dir "$env:TEMP\mase-governance-eval-smoke"` → release_gate=passed pass_rate=1.000。

未完成/待外部环境：

- **Phase 2** PostgreSQL repo、Alembic migrations、真实 tenant isolation contract tests、outbox/object store 未实现。
- **Phase 4** 真实 durable queue/worker、dead-letter、横向扩容和 load test 未实现。
- **Phase 6** OIDC/SAML/SCIM、RBAC/ABAC 完整模型、KMS/encryption、SBOM/signing、restore drill、安全评审未实现。
- 仓库仍无 `scripts/quality_gate.py`，因此当前只能标为“本地门禁通过”，不能标为完整企业生产接受。
