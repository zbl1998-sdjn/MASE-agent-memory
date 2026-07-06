# MASE 治理式记忆巩固与遗忘(白盒压缩)设计

- 状态:设计草案(2026-07-07;待多模态优化轮四收官后实施)
- 日期:2026-07-07
- 上游纲领:`MASE_whitebox_memory_governance_plan.md` 原则 2(证据先于摘要:摘要是派生物)、
  信任阶梯 E2(多来源一致的派生摘要,不能脱离原文证据);`NEXT_STEPS.md` §2.3(记忆压缩与摘要)
- 前置:P0–P7 已验收(fact_store 状态机/版本链/merge/review 通道/eval suite)
- 动机(外部佐证,2026-07-07 检索):业界黑盒记忆压缩(LLM 总结后丢原文)是 memory drift 与
  hallucinated recall 的已知失败源;MASE 的差异化是"压缩本身也是可回放、可撤销的治理动作"。

---

## 1. 目标(一句话)

把"多条旧事实 → 一条摘要事实"的压缩变成治理内动作:摘要以 **E2 派生档**落库、
`consolidates` 边指回每条被并事实,被并事实一行不改(可回放、可撤销),遗忘=留痕 retract,
永不黑盒删除。

## 2. 范围决策

| 决策点 | 选定 | 依据 |
|---|---|---|
| v1 压缩对象 | **仅 supersession 版本链**(同 key 被 supersede 的历史版本,链长 ≥ N,默认 N=4)与 expired TTL 事实 | 它们已不参与治理召回(P2 只召 active),压缩零召回风险;active 事实的语义合并留 v2 |
| 摘要生成 | **确定性模板,无 LLM**:value=该 key 取值轨迹的结构化 JSON(`[{value,observed_at,trust}...]` 按时间序),category/key 继承,claim_type=`derived_summary` | 全确定性可测;无新幻觉面;LLM 摘要+review 是 v2 增强 |
| 摘要信任级 | E2(多来源一致的派生摘要) | 信任阶梯已有此档,语义完全吻合 |
| 摘要证据 | evidence 链指回**每条成员事实的既有 evidence span**(不新造 span);`consolidates` 边逐成员一条 | 原则 2:摘要不得脱离原文证据 |
| 成员事实处置 | **一行不改**(保持 superseded/expired 原状态) | 零状态机改动、零迁移;它们本就不进召回,天然可回放 |
| 新边类型 | `fact_edges.edge_type = "consolidates"`(summary → member) | 复用 P0 版本链表;additive |
| 撤销 | `retract_fact(summary_id)` 即整体撤销(成员从未被动过) | 复用既有 retract;可逆性免费获得 |
| 遗忘门面 | `mase2_forget(fact_id, reason)` = retract + `review_actions` 留痕(`forget` 动作) | "可审计的遗忘":删除的是召回资格,不是证据 |
| 触发 | v1 显式 API `mase2_consolidate_entity(entity_id)` + CLI;engine 后台任务挂 `MASE_CONSOLIDATION=1`(默认关,复用 MASE_GC_AUTO 线程drain 机制) | 默认零行为变化,特征测试钉死 |
| 导出视图 | `export_fact_sheets.py` Superseded 节:有摘要的链折叠为摘要行 + 链长注记 | 人类可读收益立即可见 |
| 物理删除 | **永不**(既有 secret redaction 除外) | 白盒审计底线 |

## 3. 诚实边界(v1 不做)

- 不动 active 事实(语义级合并需要 LLM 判断同义,进 v2 + review 通道)。
- 不做 event log(events 表)压缩——那是另一层(topic_threads/session 摘要),不属 governance facts 面。
- 不引入热度/访问频率信号(legacy `memory_heat` 不复活;v2 再评估)。
- v1 的直接收益是**审计/导出面收敛 + 为 v2 语义巩固打治理地基**,不宣称召回精度提升
  (被压缩对象本就不参与召回,这是设计选择而非缺陷)。

## 4. 数据模型

零新表、零列变更。仅新增:
- `fact_edges.edge_type` 新值 `"consolidates"`(该列无枚举约束,additive);
- `review_actions.action` 新值 `"consolidate"` 与 `"forget"`(同上 additive);
- 摘要事实 `qualifiers_json` 记 `{"consolidation": {"member_count": N, "key": ..., "window": [t0, t1]}}`。

## 5. 模块布局

```
src/mase/governance/consolidation.py   【新】find_consolidation_candidates(entity_id, *, min_chain=4)
                                       + consolidate_chain(fact_ids) -> summary_fact_id
                                       + forget_fact(fact_id, reason)(retract + 留痕薄封装)
mase_tools/memory/api.py               mase2_consolidate_entity / mase2_forget 门面(lazy import)
scripts/export_fact_sheets.py          Superseded 节折叠视图
src/mase/engine.py                     MASE_CONSOLIDATION=1 后台任务(默认关)
```

## 6. 测试与验收(全确定性)

- gold set:同 key 5 版链 → `consolidate_chain` 产出 1 条 E2 active 摘要 + 5 条 `consolidates` 边;
  成员行 sqlite 逐字节不变(快照对比);摘要 value JSON 轨迹与 observed_at 排序一致。
- 撤销:retract 摘要后,`list_facts`/导出视图回到压缩前形态(边留痕不影响读路径)。
- 遗忘:`mase2_forget` 后该事实不进任何治理召回;`review_actions` 有 `forget` 行含 reason。
- 门槛:候选选择只含 superseded/expired;active/quarantined 混入候选 = 拒绝并留 warning。
- 特征测试:`MASE_CONSOLIDATION` 未设时 engine 行为与既有测试逐字节一致。
- 门禁:`python -X utf8 scripts/quality_gate.py --level full` 全绿;
  governance eval suite 增 consolidation lane(sample/prompt/code hash 照旧)。
