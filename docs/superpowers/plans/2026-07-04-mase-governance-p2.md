# MASE 治理 P2 实现计划(白盒召回 + Evidence Pack)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans(主会话逐任务,不开 agent,用户既定)。

**Goal:** 确定性召回 facts + 可解释 score breakdown/why_selected + Evidence Pack 编译(Verified/Conflicts/Unknowns/Do-Not-Assume)+ 检索审计可回放 + recall inspector CLI。

**Spec:** `docs/superpowers/specs/2026-07-04-mase-governance-p2-evidence-pack-design.md`(打分细则 §5,验收 §6)。

## Global Constraints

- Conventional Commits;一特性一提交;红→绿→提交;多行消息 Write 文件 + `git commit -F`。
- 测试基线 800 passed;entity_state/memory_fts 既有读路径零触碰;P0 不变式回归。
- Verified Facts 只收 active 且已定位 span(编译时机械复验,不信任上游)。
- 打分权重用 §4.5.3 原值;缺失信号记 0 并在 breakdown 如实列出,不虚构。

---

### Task 1: 两表 DDL + retrieval.py 确定性召回与打分

**Files:** Modify `mase_tools/memory/db_core.py`(3.12 节,spec §3 原样);Create `src/mase/governance/retrieval.py`;Test `tests/test_governance_retrieval.py`

**Produces:** `RetrievalPlan(trace_id, keywords, variants, filters, classifier, weights)` frozen + to_json;`ScoredCandidate(fact, score, breakdown: dict[str,float], why_selected: list[str], has_located_span: bool)`;`retrieve_facts(keywords, *, entity_id=None, db_path=None) -> tuple[RetrievalPlan, list[ScoredCandidate]]`(归一化变体 casefold/去空白/去千分位/去货币符;候选=变体 substring 命中 subject/predicate/object/entity_id 的非 rejected 事实;打分按 spec §5,分项常量 `WEIGHTS` 模块级;score 降序 fact_id 升序)。

Steps: 红(变体命中/entity 过滤/superseded 与 expired 打分惩罚/breakdown 合计=score/why 非空/并列确定序/两表存在)→ 实现 → 绿 → commit `feat(governance): deterministic fact retrieval with explainable scoring`。

### Task 2: evidence_pack.py 编译器 + 审计落库

**Files:** Create `src/mase/governance/evidence_pack.py`;Test `tests/test_evidence_pack.py`

**Produces:** `EvidencePack` frozen(spec §4 字段)+ `compile_evidence_pack(question, keywords, *, entity_id=None, top_k=8, db_path=None) -> EvidencePack` + `render_markdown(pack) -> str`(§4.6.2 五节模板,Answer Rules 固定三条:中文/区分事实建议推断/无证据标注待确认);Verified 只收 active+已定位 span(复验);Conflicts=入选事实的 conflicts_with 双方;Unknowns=零命中 keyword;Do-Not-Assume=命中的 quarantined(+secret 警示);落 retrieval_runs + context_packs(同 trace_id,token_count=len(markdown)//4)。

Steps: 红(五节内容/无证据不注入(SQL 置 NULL span)/审计两行 trace 一致/重复 compile 新 trace/markdown 渲染)→ 实现 → 绿 + 全量回归 → commit `feat(governance): evidence pack compiler with replayable audit`。

### Task 3: 门面 + recall inspector CLI

**Files:** Modify `mase_tools/memory/api.py`(`mase2_compile_evidence_pack`,lazy import 同 P0 noqa 模式,返回 dict);Create `scripts/inspect_recall.py`(sys.path 强制置顶仓根——site-packages 有同名 `scripts` 包);Test `tests/test_recall_inspector.py`

**Produces:** CLI `python -X utf8 scripts/inspect_recall.py --keywords 预算,PO-2026 [--question ...] [--entity ID] [--top-k N] [--db PATH]` → 三段输出:PLAN(json)/CANDIDATES(逐个 score+breakdown+why)/PACK(markdown);`--db` 直连指定库(验收用)。

Steps: 红(门面 dict 结构;CLI main() 对种子库返回 0 且输出含三段标题与 fact_id)→ 实现 → 绿 → commit `feat(governance): evidence pack facade and recall inspector cli`。

### Task 4: 门禁 + 真实库验收 + 收口

Steps: 门禁全套 → 用 `E:/MASE-runs/p0_acceptance/20260703T195734Z/p0.db` 跑 CLI,输出与 pack 落 `E:/MASE-runs/p2_acceptance/<ts>/`(inspect_output.txt + pack.md + evidence.md 判定)→ 人工可读检查(§8.3 三条逐条判定)→ CHANGELOG 0.11.0 + spec 状态收口 → commit `docs: close out governance P2 with acceptance evidence`。

---

## Self-Review(已执行)

Spec §3→T1;§4 retrieval→T1、pack→T2、门面/CLI→T3;§5 打分细则→T1 测试;§6 验收逐条→T2/T4;§7 非目标未越界(不动 executor 注入)。签名一致:retrieve_facts T1↔T2;compile_evidence_pack T2↔T3;trace_id 贯穿 T1/T2 审计行。
