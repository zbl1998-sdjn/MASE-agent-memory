# MASE 治理 P0 实现计划(Fact Contract + EvidenceSpan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每条长期事实成为可证明对象:FactContract v1 + 机械可验 EvidenceSpan + 状态机;无证据机械上无法 active。

**Architecture:** 新子包 `src/mase/governance/`(fact_contract 数据对象 → evidence_binder 机械定位 → fact_store 唯一写入口/状态机);db_core 仅加四表 DDL;双写接线 ingest 与 mase2_upsert_fact(可选参数,零破坏);读路径零触碰。

**Tech Stack:** 纯 Python/sqlite3,无新依赖,无模型调用(全确定性测试)。

**Spec:** `docs/superpowers/specs/2026-07-03-mase-governance-p0-fact-contract-design.md`(已批准)。

## Global Constraints

- Conventional Commits;一特性一提交;红→绿→提交;多行消息 Write 文件 + `git commit -F`。
- 测试隔离 `MASE_DB_PATH`;全量基线 725 passed;读路径(召回/注入/entity_state 查询)零改动。
- 不变式(每任务回归):**任何 API 路径都无法产生 active 且无 evidence 绑定的 fact**。
- 状态枚举:candidate/active/quarantined/superseded/retracted/rejected/expired(expired 仅字段)。
- 信任等级 E0-E5 常量对齐总纲 §4.2.3;`schema_version='fact_contract.v1'`。

---

### Task 1: 四表 DDL + fact_contract 数据对象

**Files:** Modify `mase_tools/memory/db_core.py`(_create_legacy_schema 尾部加四表,现有幂等模式);Create `src/mase/governance/__init__.py`、`src/mase/governance/fact_contract.py`;Test `tests/test_fact_contract.py`

**Produces:** `FactStatus`(str 常量集)、`TrustLevel`(E0-E5 int 常量)、`ClaimType` 常量集含 `inference`;`EvidenceSpan(evidence_id, source_type, source_id, span_start, span_end, quote_hash, quote_excerpt, trust_level, created_at)` frozen;`FactContract(fact_id, entity_id, claim_type, subject, predicate, object_value, qualifiers, status, confidence, confidence_basis, valid_from, valid_to, observed_at, visibility, sensitivity, schema_version, tenant_id, workspace_id, created_at, updated_at)` frozen + `to_row()/from_row()`;`new_fact_id()/new_evidence_id()`(uuid4 hex,前缀 fact_/ev_)。

Steps: 红测试(frozen 不可变、to_row/from_row 往返、id 前缀、schema_version 默认)→ DDL(spec §3 原样)→ 实现 → 全量回归 → commit `feat(governance): fact contract schema and value objects`。

### Task 2: evidence_binder 机械证据定位

**Files:** Create `src/mase/governance/evidence_binder.py`;Test `tests/test_evidence_binder.py`

**Produces:** `locate_evidence(evidence_text: str, source_full_text: str) -> tuple[int, int] | None`(逐字定位;先精确 find;再空白归一化容错定位——归一化后命中时把偏移映射回原文;都失败 None);`build_span(evidence_text, source_full_text, *, source_type, source_id, trust_level) -> EvidenceSpan | None`(定位成功产 span + sha256 quote_hash + ≤200 字符 excerpt)。

测试:精确命中偏移正确;仅空白差异(如 VLM 的 `P O - 2 0 2 6` vs 引用 `PO-2026`?——不,binder 只容忍**引用侧与原文侧的空白/换行差**,不做字符级模糊)命中;完全不存在 → None;quote_hash 为原文命中段的 sha256;跨行引用命中。

Steps: 红 → 实现 → 绿 → commit `feat(governance): mechanical evidence span binder`。

### Task 3: fact_store 状态机与唯一写入口

**Files:** Create `src/mase/governance/fact_store.py`;Test `tests/test_fact_store.py`

**Produces:**
```python
propose_fact(contract, evidence_text, *, source_type, source_id, trust_level, source_full_text, db_path=None) -> FactContract
retract_fact(fact_id, reason, *, db_path=None) -> bool
get_fact(fact_id, *, with_evidence=True, db_path=None) -> dict | None
list_facts(*, entity_id=None, status=None, db_path=None) -> list[dict]
supersession_chain(fact_id, *, db_path=None) -> list[dict]
```
语义(spec §4/§5):定位成功且 claim_type≠inference → active,同 (subject,predicate,qualifiers.scope,tenant,workspace) 旧 active → superseded + `fact_edges(supersedes)`;定位失败 → quarantined(evidence 仍存,excerpt=原引用文本,span NULL);inference → quarantined;retract → retracted。**不变式测试:list_facts(status='active') 每条 get_fact 都有非空 evidence 且 span 非 NULL**;直接构造无证据 active 无 API 可达。

Steps: 红(含版本链回放、幂等 propose 同内容不重复建 fact——同 quote_hash+同键+同值 → 返回既有)→ 实现 → 绿 → commit `feat(governance): fact store with status machine and supersession chain`。

### Task 4: 双写接线(ingest + mase2 门面)

**Files:** Modify `src/mase/multimodal/ingest.py`、`mase_tools/memory/api.py`;Test `tests/test_governance_dual_write.py`

**Produces:** ingest 每条事实在既有 upsert 后调用 `propose_fact`(entity_id=`media:<sha256[:12]>`,claim_type=`document_claim`,source_type=`media_extraction`,source_id=extraction_id,trust_level=E4,source_full_text=result.full_text,qualifiers={"scope": source_uri});治理层异常不打断摄取(warning 进 report.skipped? 不——新增 IngestReport 字段?最小:失败落 infra 风格列表但不判失败;实现取 `governance_warnings` 计数入 result_json?最简:tri-vault 同模式 best-effort + structured_log)。`mase2_upsert_fact` 新增可选 `evidence_text/evidence_source_type/evidence_source_id/evidence_trust_level/evidence_full_text`,给齐才双写。

测试:假抽取器 ingest → facts 表有 active 记录、evidence 反查 media_extraction 全文偏移命中、entity_state 照旧;evidence 造假(不在全文)→ quarantined;旧签名调用 mase2_upsert_fact 不产 fact(零破坏)。

Steps: 红 → 实现 → 绿 + 全量回归 → commit `feat(governance): dual-write ingestion and facade wiring`。

### Task 5: fact sheet 导出 + 门禁 + 验收

**Files:** Create `scripts/export_fact_sheets.py`;Test `tests/test_fact_sheet_export.py`

**Produces:** `python -X utf8 scripts/export_fact_sheets.py [--out DIR] [--entity ID]` → 每 entity 一个 markdown(Active/Superseded/Quarantined 三节表格:fact_id 短址/claim/evidence 源+span/observed_at),头部 front-matter 含 schema_version 与生成时间;默认 out 到 `MASE_RUNS_DIR/fact_sheets/`。

验收:①测试全绿 + README 门禁全套绿;②用 S0 验收同款样本真实 ingest 一次(qwen2.5vl+14b,GPU 与 holdout 错峰或 holdout 结束后)→ 导出 fact sheet 人工可读检查 + `无证据不可 active` 不变式在真数据上抽查。真模型验收步骤若与 holdout 抢 GPU 则排队至其后,**该步未完成前 P0 标"待验收"**。

Steps: 红 → 实现 → 绿 → 门禁 → commit `feat(governance): markdown fact sheet export`;验收后 CHANGELOG+spec 状态收口。

---

## Self-Review(已执行)

Spec 覆盖:§3→T1;§4 binder/store→T2/T3;§5 状态机→T3;§6 双写→T4;§7 测试验收→各任务+T5;§8 非目标未越界。类型一致:FactContract 字段 T1↔T3↔T4;locate/build_span 签名 T2↔T3;propose_fact 签名 T3↔T4。无占位符(T4 治理层失败处理选 best-effort+结构化日志,与 tri-vault 既有模式一致)。
