# MASE 治理 P3 实现计划(Claim Verifier + 低幻觉闭环)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans(主会话逐任务,不开 agent,用户既定)。

**Spec:** `docs/superpowers/specs/2026-07-04-mase-governance-p3-claim-verifier-design.md`。

## Global Constraints

- 基线 821 passed;engine 默认行为逐字节不变(opt-in env);Conventional Commits 一特性一提交,红→绿→提交。

### Task 1: answer_audits DDL + claim_verifier.py

**Files:** `mase_tools/memory/db_core.py`(3.13 节);Create `src/mase/governance/claim_verifier.py`;Test `tests/test_claim_verifier.py`

verify_answer(逐句 tag 按 spec §2 映射规则,violations,verdict 阈值,answer_audits 落库)+ revise_answer(标注式/refuse 文案含 unknowns)+ AnswerAudit frozen。gold set 测试全套(spec §5)。
commit `feat(governance): answer claim verifier with mechanical audit`。

### Task 2: 门面 mase2_verify_answer

**Files:** `mase_tools/memory/api.py`;Test 并入 `tests/test_claim_verifier.py`

compile pack → verify → dict(verdict/spans/violations/revised_text/trace_id)。
commit `feat(governance): answer verification facade`。

### Task 3: engine 注入开关(opt-in)

**Files:** `src/mase/engine.py`;Test `tests/test_evidence_pack_injection.py`

`MASE_EVIDENCE_PACK_INJECTION=1` 且 route=search_memory 且非 long_memory 基准链路时,fact_sheet 替换为 pack markdown(keywords=route keywords;best-effort,治理层异常回退原 fact_sheet)。特征测试:开=收到 pack;关=行为不变。
commit `feat(governance): opt-in evidence pack injection for executor`。

### Task 4: 门禁 + 真实库验收 + 收口 + 打 tag

门禁全套 → P1 真实库手写四类答案跑门面落 `E:/MASE-runs/p3_acceptance/<ts>/` → CHANGELOG 0.12.0 + spec 状态 → commit docs → 按 CHANGELOG 补打 v0.6.0/v0.7.0/v0.8.0/v0.9.0/v0.10.0/v0.11.0/v0.12.0 本地 tag(用户已批"完成后再打tag";不推远端)。
