# MASE 治理 P3 设计:Answer Claim Verifier + 低幻觉闭环

- 状态:已实现并验收(2026-07-04;门禁全绿 + 真实库四类答案验收 PASS,证据 `E:/MASE-runs/p3_acceptance/20260704T001521Z/`;verdict 规则实现期修订见 §2)
- 日期:2026-07-04
- 上游纲领:`MASE_whitebox_memory_governance_plan.md` §4.7(Answer Contract)/§8.4(P3 交付与验收);最小路径第 5 件(§13)
- 前置:P0-P2 已验收(facts/门控/冲突/EvidencePack/审计回放)

---

## 1. 目标(一句话)

让回答可被 fact/evidence 机械检查:逐句映射到 Evidence Pack,检出无支持/过时/冲突单边采信的记忆声明,自动标注修订或拒答,审计落库;注入路径提供 opt-in 的 Evidence Pack 模式。

## 2. 范围决策

| 决策点 | 选定 | 依据 |
|---|---|---|
| Claim 抽取 | **机械逐句**(中英句末标点切分,与既有 `answer_support._sentences` 同规则独立实现);不引入 LLM 抽取 | 全确定性可测;LLM 抽取是 P3.5 增强 |
| Claim→Fact 映射 | 句子归一化(P2 同款 `_norm`)后 **substring 含 verified fact 的 object 归一化形** → SUPPORTED_BY_MEMORY(记 fact_ids/evidence_ids) | 与召回同一套白盒归一化,行为一致 |
| Stale 检出 | 从 `retrieval_runs`(pack.trace_id)回放候选集,句含 superseded/expired 候选值**且不含同键 active 新值** → STALE(violation) | 审计表就是回放真源(P2 已证);同时含新旧值的对比句不是误用 |
| Unsupported 检出 | 句含候选集中 quarantined 事实值 → UNSUPPORTED_MEMORY_CLAIM(violation) | 隔离区未审核,答案不得当事实引用 |
| Conflict 检出 | 句含 pack.conflicts 任一侧值:答案**同时呈现双方值**或含"冲突"字样 → CONFLICTING(合规,显式报告);只含单侧 → violation(单边采信) | §4.7.1"report the conflict instead of choosing silently" |
| 其余句子 | UNTAGGED(不判);无一命中记忆值的答案 verdict=pass | 只审计记忆声明,不管一般内容(如实边界) |
| verdict | 无 violation → `pass`;有 violation 且 Verified 非空 → `revise`(标注修订);有 violation 且 Verified 为空 → `refuse` | 实现期修订(gold set 驱动):比例阈值会把"部分违规但有支撑"的答案误拒,refuse 收敛为零支撑场景 |
| revise | **标注式**:violation 句后插入 `〔MASE治理:<原因,fact_id>〕`;不改写原值、不二次生成 | 白盒:修订=可见警示,改写留人/上层模型 |
| refuse | 固定拒答文案 + pack.unknowns 列表("证据不足,以下未知:…") | §8.4 验收"证据不足时输出 unknown 而非编造" |
| 审计 | 新表 `answer_audits`(additive):audit_id/trace_id/answer_hash/spans_json/violations_json/verdict/created_at | §4.7.3"审计日志必须保存";总纲 §5.1 无此表,按同风格补 |
| 注入切换 | `MASE_EVIDENCE_PACK_INJECTION=1`(默认关)时 engine 在 search_memory 链路用 **pack markdown 替换 fact_sheet**(keywords=route keywords);默认行为零变化(特征测试钉死) | "LLM 面对 Evidence Pack 而非记忆仓库"(§4.7.1);opt-in 保 641+ 测试与基准不回退,全量切换待官方集评测护航 |
| 门面 | `mase2_verify_answer(question, keywords, answer, *, entity_id=None, top_k=8) -> dict`(编译 pack→verify→含 revised_text/verdict/spans) | 一步式接缝,P4 UI 与 sidecar 路由用 |

## 3. 数据模型(additive,一张表)

```sql
CREATE TABLE IF NOT EXISTS answer_audits (
    audit_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,          -- 链回 retrieval_runs/context_packs
    answer_hash TEXT NOT NULL,       -- sha256(原答案)
    spans_json TEXT NOT NULL,        -- 逐句 tag/fact_ids/violation
    violations_json TEXT NOT NULL,
    verdict TEXT NOT NULL,           -- pass|revise|refuse
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answer_audits_trace ON answer_audits(trace_id, created_at);
```

## 4. 模块布局

```
src/mase/governance/claim_verifier.py  【新】AnswerAudit(frozen)+ verify_answer(answer, pack, *, db_path)
                                       + revise_answer(audit) -> str;标签常量 SUPPORTED_BY_MEMORY/
                                       CONFLICTING/STALE/UNSUPPORTED_MEMORY_CLAIM/UNTAGGED
mase_tools/memory/db_core.py           3.13 节 answer_audits DDL
mase_tools/memory/api.py               mase2_verify_answer 门面(lazy import)
src/mase/engine.py                     MASE_EVIDENCE_PACK_INJECTION 开关(fact_sheet 替换,默认关)
```

## 5. 测试与验收(gold set 全确定性)

- **gold set**(种子库:active 800 元、superseded 500 元、冲突对 800/300、quarantined PII):
  - "预算是 800 元" → SUPPORTED(带 fact_id);
  - "预算是 500 元" → STALE violation;"预算从 500 元改为 800 元" → 含新值,非 violation;
  - "预算是 300 元" → CONFLICTING violation(单边);"存在冲突:800 元与 300 元两说" → 合规;
  - "电话 13912345678" → UNSUPPORTED violation(quarantined);
  - 编造值答案且 Verified 为空 → verdict=refuse,revised 文本含 unknowns 而非编造值。
- **unsupported claim rate 下降(§8.4 机械化)**:gold set 上原答案 violation 率 vs revise 后文本(警示标注在场)重验——所有 violation 均被显式标注,unsupported 未标注率降为 0。
- **审计**:verify 后 answer_audits 一行,trace 链回 context_packs;spans_json 可回放。
- **注入开关**:fake executor 特征测试——env 开启时 call_executor 收到 "# Memory Evidence Pack" 文本;默认关闭时 fact_sheet 与既有行为逐字节一致。
- **验收**:门禁全套绿 + P1 真实库跑门面(真实事实 + 手写四类答案)落 `E:/MASE-runs/p3_acceptance/<ts>/`。

## 6. 非目标(YAGNI)

LLM claim 抽取/复述改写、SUPPORTED_BY_CURRENT_INPUT 与 SUGGESTION/INFERENCE 标签(需输入侧语义)、sidecar 新路由与 UI(P4)、全量注入切换(待官方集评测护航)、多语言句法解析。

## 7. 风险

- substring 映射对改写体(数值换算/同义改述)漏检 → 如实定位:检出的是"逐字引用型"记忆声明,gold set 也按此口径;语义映射是 P3.5。
- 注入切换 opt-in 长期双路径 → 官方集(LongMemEval)评测后决定是否全量切,届时删旧路径。
