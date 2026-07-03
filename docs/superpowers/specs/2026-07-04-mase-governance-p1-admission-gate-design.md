# MASE 治理 P1 设计:Admission Gate + Conflict Resolver + TTL/Review

- 状态:已批准(用户 2026-07-04"出完spec直接开工")
- 日期:2026-07-04
- 上游纲领:`MASE_whitebox_memory_governance_plan.md` §4.3(G0-G7)/§4.4(冲突)/§4.1.3(状态机)/§5.1(review_actions)/§8.2(P1 交付与验收)
- 前置:P0 已验收(FactContract + EvidenceSpan + fact_store,`E:/MASE-runs/p0_acceptance/20260703T193123Z/`)

---

## 1. 目标(一句话)

防止低质量、过期、冲突、敏感事实污染记忆:写入前过确定性准入门控,冲突不静默覆盖,临时状态有 TTL,隔离事实有人工 review 通道——全部机械可执行、全程留痕。

## 2. 范围决策

| 决策点 | 选定 | 依据 |
|---|---|---|
| 门控位置 | **propose_fact 内部**执行 G2→G3→G5→G4(admission_gate 独立模块供测试与复用) | fact_store 是唯一写入口,门控挂这里则 ingest/facade 自动受控,无旁路 |
| G0(复用价值)/G7(最小必要) | **策略位就位、默认放行**(可配置谓词钩子,v1 不判) | 需要语义判断,机械规则会误杀;如实标注而非假装实现 |
| G1(证据) | 复用 P0 evidence_binder(已实现) | 不重复建设 |
| G2(可结构化) | 机械检查 subject/predicate/object 非空非纯空白;失败 → quarantined | 总纲 4.3.2 原文动作 |
| G3(敏感) | 确定性正则:**secret/token/私钥 → rejected 且值脱敏落库**(原值不落库,review_actions 记 `security_redact`);**PII(手机号/身份证/邮箱)→ quarantined + sensitivity=personal** | 总纲:secret 是 policy 拒绝(4.4.1);敏感画像必须 review(4.3.4);失败留痕哲学 |
| G5(TTL) | `tool_state` 无 valid_to 时自动设 `DEFAULT_TTL_DAYS=7`;其余类型不动 | 总纲 4.1.2:tool_state "TTL 短,默认过期" |
| G4(冲突)覆盖规则 | **trust 阶梯**(总纲 4.4.2 默认优先级的机械化):新 trust ≥ 旧 trust → supersede + 版本链 + 旧 fact `valid_to=新 observed_at`(时效闭合);新 trust < 旧 trust → 新事实 quarantined + `conflicts_with` 边(双方保留,不覆盖) | "模型推断 vs 用户显式陈述 → 用户优先""不盲目最新优先";decision_score 全公式留 P2+ |
| 冲突判定粒度 | 同键 (subject, predicate, scope, tenant, workspace) 且 **object 不同**;object 相同走 P0 幂等 | 4.4.1 Scope mismatch:scope 不同即不冲突(P0 已实现) |
| review 队列 | **不加新状态/新列**:队列 = `list_facts(status='quarantined')`;`approve_fact/reject_fact` 写 review_actions 表 | 总纲状态机 quarantined --human_approve--> active;最小 schema |
| approve 守不变式 | approve 仅当该 fact 存在**已定位 span**(span 非 NULL)才转 active;否则拒绝并说明 | P0 不变式"active 必有已定位证据"不可破——人工也不能豁免机械可验性 |
| expired 执行 | 惰性 + 显式双轨:`expire_due_facts()` 批量迁移;`list_facts`/`get_fact` 读到 active 且 `valid_to < now` 时先写回 expired 再返回 | 无守护进程依赖,读到即一致 |

## 3. 数据模型(additive:一张表,零改列)

```sql
CREATE TABLE IF NOT EXISTS review_actions (
    review_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    action TEXT NOT NULL,          -- approve|reject|security_redact
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_actions_fact ON review_actions(fact_id, created_at);
```

## 4. 模块布局

```
src/mase/governance/
  admission_gate.py     【新】GateDecision(action, gate, reason) + 纯函数门链:
                        check_structurable(G2) / scan_sensitive(G3,返回 secret|pii|clean 及命中模式名)
                        / apply_ttl_policy(G5) / evaluate_admission(汇总,不碰库)
  conflict.py           【新】resolve_conflict(new_trust, old_trust) -> supersede|quarantine_new
                        + 纯决策函数(库操作仍在 fact_store)
  fact_store.py         【改】propose_fact 编排:G2→G3→G5→binder(G1)→G4;
                        新增 approve_fact / reject_fact / expire_due_facts / list_review_queue
mase_tools/memory/db_core.py   仅加 review_actions DDL
scripts/export_fact_sheets.py  页脚计数已覆盖 rejected/expired(不改结构)
```

**新增 API(P2/P3 的接缝):**

```python
approve_fact(fact_id, *, reviewer, reason=None, db_path=None) -> tuple[bool, str]
reject_fact(fact_id, *, reviewer, reason=None, db_path=None) -> tuple[bool, str]
expire_due_facts(*, now=None, db_path=None) -> int          # 返回迁移条数
list_review_queue(*, db_path=None) -> list[dict]            # quarantined + 证据 + 冲突边
```

## 5. propose_fact 门控流水(v1 全序)

```
candidate contract
  G2 不可结构化 ────────────→ quarantined(gate 留痕在 confidence_basis_json.gate)
  G3 secret 命中 ───────────→ rejected + 值脱敏 "[REDACTED:<pattern>]" + review_actions(security_redact)
  G3 PII 命中 ──────────────→ 继续,但强制 sensitivity=personal,终态封顶 quarantined
  G5 tool_state 无 valid_to → 自动 valid_to = observed_at + 7d
  G1 binder 定位失败 ────────→ quarantined(P0 既有)
  claim_type=inference ─────→ quarantined(P0 既有)
  G4 同键旧 active 且值不同:
      新 trust ≥ 旧 trust → 旧 superseded + supersedes 边 + 旧 valid_to 闭合
      新 trust < 旧 trust → 新 quarantined + conflicts_with 边(新→旧)
  全部通过 → active
```

所有非 active 终态在 `confidence_basis_json.gate` 记 `{gate, reason}`——失败可解释。

## 6. 与 P0 的行为变化(唯一一处)

P0 的同键 supersede 是无条件的;P1 起看 trust 阶梯。既有双写路径(ingest E4、facade 显式 trust)行为不变(同 trust → supersede 照旧);只有"低 trust 新值试图顶替高 trust 旧值"从 supersede 变为 quarantined+conflict——这正是 §8.2 验收项"冲突事实不会被静默覆盖"。P0 特征测试若钉了无条件 supersede,按新契约更新断言并在提交信息说明。

## 7. 测试与验收(全确定性,不碰真模型)

- **G2**:空 predicate/空 object → quarantined,gate 留痕。
- **G3 secret**:`api_key=dummy123…`(占位样式)、PEM 私钥块头样式(BEGIN…PRIVATE KEY)、AKIA 样式 → rejected,落库值为 `[REDACTED:*]`,原文不出现在任何列;review_actions 有 security_redact 行。测试用占位凭据并按仓规加 `allowlist-secret` 注释。
- **G3 PII**:含手机号样式值 → quarantined 且 sensitivity=personal;evidence 正常留痕。
- **G5**:tool_state 无 valid_to → 自动 +7d;显式给了 valid_to 不覆盖;preference 不设。
- **G4**:E5 旧事实 + E1 新值 → 旧仍 active、新 quarantined、conflicts_with 边存在;E4→E5 反向 → supersede + 旧 valid_to 闭合。**偏好变更样本(同 trust)正确 supersede**(§8.2 验收原文)。
- **TTL**:构造 valid_to 已过的 active → expire_due_facts() 迁移 expired;list_facts(active) 惰性不再返回它。
- **review**:approve 已定位 quarantined → active(不变式复验);approve 无 span 事实 → 拒绝;reject → rejected;review_actions 全留痕;队列可列出冲突上下文。
- **回归**:P0 全部测试 + 全量基线零回退(除 §6 声明的契约更新);门禁全套绿。
- **真实面**:P1 无新模型面;重跑 `scripts/run_p0_acceptance.py` 仍 PASS 即收口(真实 ingest 路径过全套新门控)。

## 8. 非目标(YAGNI)

decision_score 九项全公式、Granularity/Alias 语义冲突、Evidence Pack 与注入等级 C0-C5(P2)、Claim Verifier(P3)、Review UI(P4,本期只有库函数与 fact sheet 可视)、ephemeral store 独立存储(G5 用 valid_to 表达)、prompt-injection 语义检测(E0 深检测留后,v1 只有 secret/PII 正则)。

## 9. 风险

- 正则敏感检测有漏报(语义变体)→ 如实定位为"基础检测"(§8.2 原文也只要求 basic);漏报走 review 通道兜底,检测模式集中一处便于增补。
- trust 阶梯对"同 trust 直接矛盾"仍会 supersede → 版本链+valid_time 可回放,非静默丢失;真矛盾显性化的语义判定留 P2 冲突报告。
- 惰性过期使读路径带写 → 仅治理层自身 API(entity_state 读路径 P1 仍零触碰),锁窗口极小。
