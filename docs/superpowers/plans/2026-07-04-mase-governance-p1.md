# MASE 治理 P1 实现计划(Admission Gate + Conflict + TTL/Review)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans(主会话逐任务,不开 agent,用户既定)。

**Goal:** 写入前确定性准入门控(G2/G3/G5)、trust 阶梯冲突治理(G4,不静默覆盖)、TTL 过期执行、quarantined 人工 review 通道;全程留痕。

**Spec:** `docs/superpowers/specs/2026-07-04-mase-governance-p1-admission-gate-design.md`(已批准,门控全序见 §5)。

## Global Constraints

- Conventional Commits;一特性一提交;红→绿→提交;多行消息 Write 文件 + `git commit -F`。
- 测试基线 766 passed;entity_state 读路径零触碰;P0 不变式(active 必有已定位 span)每任务回归。
- 唯一预期契约变化(spec §6):低 trust 新值不再 supersede 高 trust 旧 active。
- 测试里的假密钥一律占位样式(dummy/fake)+ 必要时 `allowlist-secret` 注释,不写真实样式凭据。

---

### Task 1: review_actions DDL + admission_gate 纯函数

**Files:** Modify `mase_tools/memory/db_core.py`(3.11 节加 review_actions,spec §3 原样);Create `src/mase/governance/admission_gate.py`;Test `tests/test_admission_gate.py`

**Produces:** `GateDecision(action, gate, reason)` frozen(action ∈ pass|quarantine|reject);`check_structurable(contract) -> GateDecision`(G2:subject/predicate/object 非空非纯空白);`scan_sensitive(*texts) -> GateDecision`(G3:secret 正则组 → reject 带命中模式名;PII 正则组 → quarantine;全净 → pass;模式常量集中 `SECRET_PATTERNS`/`PII_PATTERNS`);`apply_ttl_policy(contract) -> FactContract`(G5:tool_state 无 valid_to → replace 出 valid_to=observed_at+7d,`DEFAULT_TTL_DAYS=7`;其余原样返回)。纯函数不碰库。

Steps: 红(G2 空值各形态;G3 secret 三样式/PII 手机号身份证邮箱/干净文本;G5 设与不设/非 tool_state)→ 实现 → 绿 → commit `feat(governance): admission gate rules and review actions schema`。

### Task 2: fact_store 集成 G2/G3/G5 + 脱敏留痕

**Files:** Modify `src/mase/governance/fact_store.py`;Test `tests/test_fact_store_gates.py`

**Produces:** propose_fact 按 spec §5 顺序编排:G2 失败 → quarantined;G3 secret → **rejected 且 object_value/quote_excerpt 落库为 `[REDACTED:<pattern>]`(原值不落任何列)** + review_actions 记 `security_redact`(reviewer=`system:gate`);G3 PII → 强制 sensitivity=personal 且终态封顶 quarantined;G5 自动 valid_to。非 active 终态在 `confidence_basis_json` 合并 `{"gate": {...}}`。

Steps: 红(secret 值/secret 在 evidence、PII 值、空 predicate、tool_state TTL、干净事实仍 active、P0 幂等与不变式回归)→ 实现 → 绿 + 全量回归 → commit `feat(governance): wire admission gates into fact store with redaction`。

### Task 3: G4 冲突 trust 阶梯 + conflicts_with + valid_time 闭合

**Files:** Create `src/mase/governance/conflict.py`;Modify `src/mase/governance/fact_store.py`;Test `tests/test_conflict_resolver.py`

**Produces:** `resolve_conflict(new_trust, old_trust) -> str`(supersede|quarantine_new,纯决策);propose_fact 同键值不同才走 G4:supersede 分支加**旧 fact valid_to=新 observed_at**;quarantine_new 分支新事实 quarantined + `fact_edges(new→old, 'conflicts_with')`,旧 active 不动。旧 fact trust 取其证据最高 trust_level。

Steps: 红(E5←E1 不覆盖+边;E4→E5 覆盖+旧 valid_to 闭合;同 trust 偏好变更 supersede——§8.2 验收原文;值相同仍幂等)→ 实现 → 绿(P0 test_fact_store 若钉无条件 supersede 按 spec §6 更新断言)→ commit `feat(governance): trust-ladder conflict resolver with explicit conflict edges`。

### Task 4: TTL 执行 + review 通道

**Files:** Modify `src/mase/governance/fact_store.py`;Test `tests/test_ttl_and_review.py`

**Produces:** `expire_due_facts(*, now=None, db_path=None) -> int`(active 且 valid_to<now → expired);list_facts/get_fact 惰性:命中过期 active 先写回再返回;`approve_fact/reject_fact(fact_id, *, reviewer, reason=None, db_path=None) -> tuple[bool, str]`(approve 仅限 quarantined 且有已定位 span → active,否则 (False, 原因);reject → rejected;都写 review_actions);`list_review_queue()`(quarantined + evidence + conflicts_with 对端摘要)。

Steps: 红(过期迁移/惰性/未到期不动;approve 有 span→active 且不变式复验;approve 无 span 拒;approve 非 quarantined 拒;reject;review_actions 留痕;队列含冲突上下文)→ 实现 → 绿 → commit `feat(governance): ttl expiry and human review channel`。

### Task 5: 门禁 + 真实回归 + 收口

**Files:** Modify `CHANGELOG.md`、spec 状态行;(fact sheet 页脚已覆盖新状态,确认即可)

Steps: 门禁全套(pytest/ruff/mypy/compileall/hygiene/anti-overfit/前端三门)→ 重跑 `python -X utf8 scripts/run_p0_acceptance.py`(真实 ingest 过新门控仍 PASS)→ CHANGELOG 0.10.0 + spec 状态"已实现并验收" → commit `docs: close out governance P1 with acceptance evidence`。

---

## Self-Review(已执行)

Spec §5 全序 → T2(G2/G3/G5)+T3(G4)+P0 既有(G1/inference);§3 → T1;§4 API → T4;§7 测试项逐条映射各任务红测试;§6 契约变化在 T3 显式处理;§8 非目标未越界。签名一致:GateDecision T1↔T2;resolve_conflict T3 内;review API T4↔spec §4。
