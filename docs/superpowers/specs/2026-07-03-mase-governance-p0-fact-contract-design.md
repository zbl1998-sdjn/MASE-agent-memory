# MASE 治理 P0 设计:Fact Contract v1 + EvidenceSpan v1

- 状态:草案(待用户审阅)
- 日期:2026-07-03
- 上游纲领:`MASE_whitebox_memory_governance_plan.md` §4.1/§4.2/§8.1(最小路径第 1 件)
- 哲学判据:对照总纲 §14 七条(减少无证据写入/可解释/确定性测试/可撤回回放/失败留痕)

---

## 1. 目标(一句话)

让每条长期事实成为**可证明对象**:结构化 FactContract + 机械可验的 EvidenceSpan 绑定 + 状态机;**无证据的事实机械上无法成为 active**。

## 2. 范围决策(接续现状,不推倒重来)

| 决策点 | 选定 | 依据 |
|---|---|---|
| 与 entity_state 的关系 | **共存双写**:facts 四表为治理层新真源,entity_state 保持现有读路径的兼容投影;P0 不改任何召回/注入路径(那是 P2) | 641+ 既有测试与 LV-Eval 等基准全部压在 entity_state 读路径上;大爆炸替换违反"改动前特征测试钉死"纪律 |
| 首批接线的生产者 | ①多模态 ingest(证据=media_extraction 全文中的 span);②notetaker/upsert 门面(证据=memory_log 事件行) | 两者已有溯源雏形(source_media_id / source_log_id),P0 是把雏形正式化 |
| 证据验证方式 | **机械验证**:CandidateFact.evidence 必须能在来源全文中逐字定位(substring find → span offsets + quote_hash);定位失败 → 状态 quarantined 而非 active | 把"evidence 必须引用原文"从提示词约定升级为不可绕过的门 |
| 状态机范围 | v1 实现 candidate/active/quarantined/superseded/retracted/rejected;expired 字段就位但 TTL 执行留 P1 | 总纲 §8.1/§8.2 的边界划分 |
| 冲突处理 | P0 只做**同键新事实自动 supersede + fact_edges 记链**;冲突显性化决策留 P1 Conflict Resolver | 最小可行,不预支 P1 |

## 3. 数据模型(additive,四表 + 常量)

对齐总纲 §5.1,收敛到 v1 最小字段(总纲 §12"schema 太重"风险的缓解):

```sql
CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,              -- uuid4 hex
    entity_id TEXT NOT NULL,               -- 如 user:default / media:<sha12> / thread:<id>
    claim_type TEXT NOT NULL,              -- preference|profile|project_fact|document_claim|tool_state|inference
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,               -- 对应现有 entity_key 语义
    object TEXT NOT NULL,                  -- 对应现有 entity_value
    qualifiers_json TEXT,                  -- scope 等
    status TEXT NOT NULL,                  -- candidate|active|quarantined|superseded|retracted|rejected|expired
    confidence REAL NOT NULL,
    confidence_basis_json TEXT,
    valid_from TEXT, valid_to TEXT,
    observed_at TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private',
    sensitivity TEXT NOT NULL DEFAULT 'normal',
    schema_version TEXT NOT NULL DEFAULT 'fact_contract.v1',
    tenant_id TEXT NOT NULL DEFAULT '', workspace_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_facts_subject_pred ON facts(subject, predicate, status);

CREATE TABLE IF NOT EXISTS evidence_spans (
    evidence_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,             -- media_extraction|memory_log|file|manual_entry
    source_id TEXT NOT NULL,               -- extraction_id / log_id / 路径+sha
    span_start INTEGER, span_end INTEGER,  -- 在来源全文中的字符偏移
    quote_hash TEXT NOT NULL,              -- sha256(引用原文)
    quote_excerpt TEXT,                    -- ≤200 字符引文(人读;完整原文经 source 反查)
    trust_level INTEGER NOT NULL,          -- E0-E5,总纲 §4.2.3
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_evidence (
    fact_id TEXT NOT NULL, evidence_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'supports',
    PRIMARY KEY (fact_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS fact_edges (
    from_fact_id TEXT NOT NULL, to_fact_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,               -- supersedes|conflicts_with(P1 用)
    created_at TEXT NOT NULL,
    PRIMARY KEY (from_fact_id, to_fact_id, edge_type)
);
```

## 4. 模块布局(遵循总纲 §10 目录方向,落在现仓结构)

```
src/mase/governance/            【新子包】
  fact_contract.py              FactContract/EvidenceSpan frozen dataclass + 状态枚举 + schema_version
  fact_store.py                 四表 CRUD + 状态迁移(唯一写入口,状态机在此强制)
  evidence_binder.py            机械证据定位:evidence 文本 → 来源全文 substring → span/quote_hash;
                                找不到 → 返回 None(调用方降级 quarantined)
mase_tools/memory/db_core.py    仅加四表 DDL(现有幂等模式)
src/mase/multimodal/ingest.py   双写:每条 CandidateFact → propose_fact(evidence=extraction 全文定位)
mase_tools/memory/api.py        mase2_upsert_fact 增可选 evidence 参数透传双写(不破坏既有签名)
scripts/export_fact_sheets.py   Markdown fact sheet 导出(active/superseded/quarantined 分节)
```

**FactStore 核心 API(后续 P1-P3 的接缝):**

```python
propose_fact(contract: FactContract, evidence_text: str, source_type: str, source_id: str,
             *, trust_level: int) -> FactContract
# 内部:evidence_binder 定位 → 成功: status=active + span 绑定 + 同键旧 active 自动 superseded(fact_edges 记链)
#       失败: status=quarantined(留原文引文供 review)
# inference 类 claim_type 一律 quarantined(总纲 §4.1.2)
retract_fact(fact_id, reason) / get_fact(fact_id, with_evidence=True)
list_facts(entity_id=None, status=None) / supersession_chain(fact_id)
```

## 5. 状态机(v1 执行子集)

```
candidate --evidence located & type allowed--> active(同键旧 active → superseded + edge)
candidate --evidence NOT located------------> quarantined
candidate --claim_type=inference------------> quarantined
active    --retract_fact()------------------> retracted
candidate --显式拒绝-------------------------> rejected
(expired:字段就位,TTL 执行 P1)
```

不变式(测试钉死):**任何路径都无法产生"active 且无 evidence_spans 绑定"的事实**——包括直接 SQL 之外的全部 API 面。

## 6. 双写语义与兼容

- ingest 对每条抽取事实:先走现有 `mase2_upsert_fact`(entity_state,读路径零变化),再 `propose_fact`(治理层)。**双写失败互不阻塞**(治理层失败落 warning,不打断摄取;审计可见)。
- notetaker 路径:`mase2_upsert_fact` 新增可选 `evidence_text/source_type/source_id`;传了就双写,没传(旧调用方)只写 entity_state——**零破坏迁移**,治理覆盖率成为可度量指标(而非一夜切换)。
- 召回/注入路径 P0 完全不动。

## 7. 测试与验收(全确定性,不碰真模型)

- **不变式**:propose 无法定位证据 → quarantined;定位成功 → active + span 偏移/quote_hash 正确;inference → quarantined;retract 后 list_facts(active) 不含。
- **版本链**:同 (subject, predicate, scope) 第二次 propose → 旧 active 变 superseded,fact_edges 有 supersedes 边,chain 可回放。
- **双写**:ingest 假抽取器端到端 → entity_state 与 facts 各一条,fact 的 evidence 反查 media_extraction 全文命中 span。
- **导出**:export_fact_sheets 产出含 Active/Superseded/Quarantined 三节的 markdown,内容与库一致。
- **回归**:既有全量测试零回退(读路径未动,机械保证)。
- 验收 = 上述测试绿 + README 门禁全绿 + 一次真实 ingest(可复用 S0 验收样本)产出的 fact sheet 人工可读检查。真模型面不新增(P0 是纯治理层)。

## 8. 非目标(YAGNI,留给后续 P)

准入门控 G0-G7 全集/敏感检测(P1)、冲突显性化决策(P1)、TTL 执行(P1)、检索计划编译与 Evidence Pack(P2)、答案验证(P3)、Review UI(P4)、文档 page/line map(P5)、Policy DSL、Provenance Graph 全图。

## 9. 风险

- 双写漂移(entity_state 与 facts 不一致)→ P0 接受(治理层是增量真源,漂移可被 export+diff 观测);P2 收敛读路径时统一。
- evidence 逐字定位对 LLM 输出的鲁棒性 → 已有管道行契约要求 evidence 引原文,定位失败即 quarantined 本身就是质量信号(可进指标)。
- schema 演进 → schema_version 字段就位,v1 字段刻意最小。
