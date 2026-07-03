# MASE 治理 P2 设计:白盒召回 + Evidence Pack Compiler

- 状态:已批准(用户 2026-07-04"把p2的spec出来,然后开始建成吧")
- 日期:2026-07-04
- 上游纲领:`MASE_whitebox_memory_governance_plan.md` §4.5(白盒召回/可解释打分)/§4.6(Evidence Pack/注入等级)/§5.1(retrieval_runs、context_packs)/§8.3(P2 交付与验收)
- 前置:P0/P1 已验收(facts 治理层有 active/quarantined/conflicts_with/review 全套语义)

---

## 1. 目标(一句话)

从"检索文本"升级为"编译证据包":对治理层 facts 做确定性召回,每个候选给可解释 score breakdown 与 why_selected,编译成含 Verified Facts / Conflicts / Unknowns / Do-Not-Assume 的结构化 Evidence Pack,检索与编译全程落审计表可回放。

## 2. 范围决策

| 决策点 | 选定 | 依据 |
|---|---|---|
| 召回数据源 | **治理层 facts 表**(P0/P1 产物);entity_state/memory_fts 既有读路径零触碰 | "接续现状":641+ 测试压在旧读路径上;P2 先把新路径建成可用、可审计,executor 注入切换留 P3(届时 Claim Verifier 需要 pack,一起换) |
| Query Classifier / Entity Resolver | **v1 不做分类器**;调用方直接给 keywords(与 mase2_search_memory 同约定),entity_id 可选过滤 | §4.5.2 管线的这两级需要语义;v1 保持机械,plan_json 里如实记 `classifier: "none.v1"` |
| 确定性检索 | keywords casefold + 归一化变体(去空白/千分位/货币符,复用 P6 优化轮同思路)对 subject/predicate/object/entity_id 做 substring 匹配;status/valid_time 过滤(active 且未过期才可成为 Verified) | §4.5.2 Deterministic Retrieval;FTS5 面向 memory_log,facts 量级小(全表扫描 + 索引过滤足够) |
| Controlled Expansion | **v1 只有机械归一化变体**(白盒可列举,进 plan_json);同义词/领域词典表留 P2.5(需要人工维护来源) | §4.5.1:扩展词必须可见有来源——空词典就是最诚实的起点 |
| Embedding Discovery | 不做 | 总纲允许"可选";非最小路径 |
| 打分 | §4.5.3 公式的**可用信号子集**,权重原样保留、缺失信号记 0 并在 breakdown 中如实列出:exact_entity_match(0.30)/predicate_match(0.20)/evidence_strength(0.15,已定位 span 的最高 trust/5)/recency_or_validity(0.10,active 未过期=1)/scope_match(0.10,给了 scope 过滤且命中)/tag_match(0.05,v1 恒 0)/source_trust(0.05,trust/5)/reviewer_status(0.05,有 approve 记录=1)- conflict_penalty(0.30,有 conflicts_with 对手)- staleness_penalty(0.20,valid_to 已过)- sensitivity_penalty(0.20,personal/confidential/secret) | 公式白盒、每项独立可测;比发明新公式更忠实 |
| 选取规则 | score 降序取 top_k(默认 8);**Verified Facts 只收 status=active 且有已定位 span**(编译时机械复验,不信任上游) | §8.3 验收原文"无证据候选不得注入" |
| 注入等级 | v1 实现 C0(不入选)/C2(verified:claim+evidence)/C3(冲突:双方+warning)/C5(Do-Not-Assume);C1(摘要)/C4(policy 类)留后 | v1 无摘要生成器、无 policy claim 生产者,如实缺席 |
| Conflicts 节 | 入选 fact 若有 `conflicts_with` 边(任一方向),把对手(含 quarantined)双方 claim 并列 + warning | §4.6.3 C3;P1 的显性边在此兑现价值 |
| Unknowns 节 | 无任何候选命中的 keyword → "尚无记忆事实覆盖" | §4.6.2 模板;把"检索不到"显性化而非沉默 |
| Do-Not-Assume 节 | 命中 keywords 的 quarantined 事实 → "未审核,不得当已确认";sensitivity=secret 相关 → "不得使用" | §4.6.2/C5;隔离区不注入但要警示 |
| token_count | **字符数/4 的确定性估算**,pack 里字段名 `token_estimate` 语义如实(库列名从 §5.1 的 token_count) | 无 tokenizer 依赖;诚实标注估算 |
| 审计落库 | 每次 compile:retrieval_runs(plan/candidates/selected 全 JSON)+ context_packs(fact_ids/evidence_ids/conflicts/unknowns/token_count);trace_id 贯穿 | §5.1 原样;"每一次检索可回放" |
| 入口 | 库 API `compile_evidence_pack(question, keywords, *, entity_id=None, top_k=8, db_path=None)`;门面 `mase2_compile_evidence_pack`(lazy import 同 P0 模式);CLI `scripts/inspect_recall.py`(打印 plan→candidates(score breakdown)→pack markdown) | §8.3 交付含 recall inspector CLI |

## 3. 数据模型(additive,两表,§5.1 原样)

```sql
CREATE TABLE IF NOT EXISTS retrieval_runs (
    retrieval_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    query TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    selected_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS context_packs (
    context_pack_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    question_hash TEXT NOT NULL,
    fact_ids_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    conflicts_json TEXT,
    unknowns_json TEXT,
    token_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
```

## 4. 模块布局

```
src/mase/governance/
  retrieval.py        【新】RetrievalPlan/ScoredCandidate;
                      retrieve_facts(keywords, *, entity_id=None, db_path=None)
                        -> (RetrievalPlan, list[ScoredCandidate])
                      纯确定性:归一化变体 → 候选 → 逐项打分 breakdown + why_selected
  evidence_pack.py    【新】EvidencePack(frozen)+ compile_evidence_pack(...)
                        -> EvidencePack;render_markdown(pack) -> str(§4.6.2 模板);
                      落 retrieval_runs + context_packs(同一 trace_id)
mase_tools/memory/db_core.py   3.12 节加两表 DDL
mase_tools/memory/api.py       mase2_compile_evidence_pack 门面(lazy import,best-effort 无)
scripts/inspect_recall.py      recall inspector CLI(--keywords/--entity/--top-k/--db)
```

**EvidencePack 字段**:`pack_id/trace_id/question/verified(list[dict: fact_id,claim,evidence_ref,validity,score,why_selected)]/conflicts(list[dict: warning,sides])/unknowns(list[str])/do_not_assume(list[str])/token_estimate/created_at`。

## 5. 打分与选取细则

- 匹配变体(全部进 plan_json 可见):casefold、去空白、去千分位逗号、去货币符($¥€)。
- `exact_entity_match`:keyword 变体与 entity_id 或 subject 完全相等=1,子串=0.5。
- `predicate_match`:keyword 变体命中 predicate=1;命中 object=0.8 记入 predicate_match(值命中,v1 并入该项并在 why 里注明)。
- `evidence_strength`:该 fact 已定位 span 的 max(trust)/5;无已定位 span=0(且永不入 Verified)。
- `reviewer_status`:review_actions 有 approve 记录=1。
- 每个非零/非缺省项生成一条 why_selected 人话(中文,含命中词与命中列)。
- 候选按 score 降序、fact_id 升序(确定性并列裁决)取 top_k。

## 6. 测试与验收(全确定性,不碰真模型)

- **召回**:种子库(active/quarantined/superseded/expired/conflict 对)→ keywords 命中 active;superseded/expired 不入 Verified;entity 过滤生效;归一化变体命中(千分位/空白差)。
- **打分**:每个 selected 候选 breakdown 各分项与公式合计一致;why_selected 非空且提及命中词;并列时排序确定。
- **无证据不注入**:手工把某 active 事实的 span 置 NULL(直接 SQL 模拟脏数据)→ compile 拒绝其入 Verified 并落 warning。
- **Pack 结构**:conflicts 节含双方 claim + warning;unknowns 含未命中 keyword;do_not_assume 含 quarantined 命中项;markdown 渲染含五节(Verified/Conflicts/Unknowns/Do Not Assume/Answer Rules)。
- **审计回放**:compile 后 retrieval_runs/context_packs 各一行,trace_id 一致,candidates_json 含全部候选的 breakdown;同问题重复 compile 产生新 trace(不覆盖)。
- **门面/CLI**:mase2_compile_evidence_pack 返回 dict;CLI 对种子库输出人可读三段(plan/candidates/pack)。
- **验收**:门禁全套绿 + 用 P0 验收真实库(`E:/MASE-runs/p0_acceptance/20260703T195734Z/p0.db`)跑 CLI,pack 人工可读检查落证据文件(`E:/MASE-runs/p2_acceptance/<ts>/`)。§8.3 三条逐一对应:why_selected ✓、四节齐全 ✓、无证据不注入 ✓。

## 7. 非目标(YAGNI)

executor/chat 注入路径切换(P3 与 Claim Verifier 一起)、Query Classifier/Entity Resolver 语义层、同义词/tag 词典与 tag_match 实值、embedding discovery、C1/C4 注入等级、token 精确计数、tri-vault §5.2 目录扩展、Review UI。

## 8. 风险

- facts 全表扫描 + Python 打分在事实量大时变慢 → v1 facts 量级(百~千)可忽略;plan_json 记录候选数,超阈值时是 P2.5 加索引/FTS 的信号。
- 值命中并入 predicate_match 造成语义混叠 → why_selected 里区分注明,breakdown 忠实可审计。
- 新读路径与旧路径暂时并存(双真源读侧漂移)→ P0 已声明接受;P3 切换时以 pack 为准收敛。
