# MASE 弱语义线索节(Weak Semantic Hints)设计

- 状态:已实现并验收(2026-07-07 同日;诊断面 run `semantic_recall_20260707T005222Z`:Verified 面 0.75/0 噪声/0 误发现保持,hint_recovery 3/16 与取证预测一致,effective_coverage 0.9375;§3 验收逐条通过,测试 935→939)
- 日期:2026-07-07
- 上游:语义召回校准记录(`benchmarks/semantic_recall/README.md` 2026-07-07 节)
  ——负例顶点 0.514 与最弱真目标 0.538 分界极窄,精确档(0.55)必然漏掉
  0.50–0.55 区间的真改写;取证证明 top1-top2 边际差无区分度(负例恰是孤立
  低分),"自适应调阈"被数据否决 → 正解是**分层**而非调阈
- 前置:语义发现 v1(0987ef95)、Evidence Pack(P2)、Claim Verifier(P3)

---

## 1. 目标(一句话)

高精确与高召回不再互斥:Verified 永远走精确档(0.55)零污染;相似度落在
`[hint_floor, threshold)` 的语义候选进 Evidence Pack 的**非应答**"弱语义线索"
节,供上层追问("你是想问 X 吗?"),不作任何事实依据。

## 2. 范围决策

| 决策点 | 选定 | 依据 |
|---|---|---|
| 线索带 | `[MASE_SEMANTIC_HINT_FLOOR(默认 0.50), threshold)`,cap 3 条 | 校准数据:3/4 的精确档漏检落在此带;floor=threshold 即关闭线索 |
| 计算路径 | 复用同一次 discover 调用(threshold=floor 取全带,retrieval 内分带) | 零额外 embed;单次查询向量 |
| 承载 | 线索挂 `plan.filters["semantic"]["hints"]`(fact_id+similarity) | plan_json 自动入 retrieval_runs 审计;retrieve_facts 签名零变更 |
| 候选隔离 | 线索**不是** ScoredCandidate:不打分、不进 top_k、不参与冲突收集 | 应答面与线索面物理隔离 |
| pack 形态 | `EvidencePack.semantic_hints: tuple[dict,...] = ()`(additive 默认空);渲染为条件节"## Weak Semantic Hints(非应答)",置于 Do Not Assume 之后 | 默认关/无线索时 to_dict 与 markdown 既有节逐字节不变(Warnings 条件节先例) |
| 线索准入 | 仅 status=active 且 sensitivity=normal 的事实可作线索 | 线索会显露 claim 原文;隔离区/敏感值绝不经此泄出 |
| verifier 口径 | 不改:线索不在候选集,答案引用线索值 → UNTAGGED(如实不判) | 线索定位是"促追问",不是应答材料;引用即脱离治理支撑,v2 再议专属标签 |
| 追问文案 | 渲染层给建议句式("可能相关…不作应答依据"),真正追问交给上层 | 治理层不做产品决策 |

## 3. 验收

- 默认关 / flag 开但无带内候选:pack.to_dict 与 markdown 与现行为逐字节一致(特征测试);
- 假向量:0.60 → Verified;0.52 → 仅 hints 节 + plan 审计,不进候选/冲突;0.45 → 无处出现;
- 敏感/隔离事实即使落带也不出现在 hints;
- 诊断面新增指标:`hint_recovery`(精确档漏检被线索带接住的比例)——预期 3/4;
- quick 闸全绿;诊断面重跑数据入 README。
