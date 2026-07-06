# MASE 时漂压力基准(Staleness Pressure Benchmark)设计

- 状态:设计草案(2026-07-07;待治理式巩固 v1 之后或并行实施)
- 日期:2026-07-07
- 上游:governance eval suite(P7,`src/mase/governance/eval_suite.py` 已有
  deterministic / anti_poisoning / stale_conflict lane 雏形);`docs/BENCHMARK_ANTI_OVERFIT.md`
- 动机(外部佐证,2026-07-07 检索,厂商自报未独立复核):业界共识是记忆系统 benchmark
  平均 ~91% 而生产 30 天 staleness 后掉到 55–70%,主因 stale data / 实体矛盾 / 时间建模缺失
  ——这三样正是 MASE supersede + valid_time + conflicts_with + trust ladder 的设计目标。
  把这个差距做成基准,是"主场作战"而非追分。

---

## 1. 目标(一句话)

用确定性生成的"知识更新密集 + 冲突注入 + 时间漂移"场景,量化 MASE 在记忆变旧时
**不引用过时值、不静默单边采信、正确采用新值**的能力,输出可回放的压力曲线
(t=0/7/30/90 天四档),作为治理层的常设回归面。

## 2. 场景生成器(全确定性,种子固定)

| 场景族 | 构造 | 考察 |
|---|---|---|
| knowledge-update 链 | 同 key 依次写入 v1..vn(observed_at 递进,trust 混排 E1–E4) | 召回/回答只用最新 active 值;低 trust 新值不得顶掉高 trust 旧值(应 quarantined) |
| 实体矛盾对 | 同 key 双来源不同值,trust 相同(应 conflicts_with 双陈列) | 回答显式报告冲突,单边采信=fail |
| TTL 漂移 | tool_state 类事实注入后推进模拟时钟越过 valid_to | 过期值出现在答案=fail(STALE) |
| 陈旧诱导问答 | 问题措辞锚定旧值("还是 X 吗?") | 回答须给现行值或显式说明已更新 |
| 干扰弃答 | 询问从未入库的 key | 输出 unknown 而非编造(refuse/unknowns) |

- 模拟时钟:场景内所有 observed_at/valid_to/查询时刻由生成器显式给定,不取系统时间
  (与 workflow/回放约束一致);t 档位 = 查询时刻相对最后写入的偏移(0/7/30/90 天)。
- 规模:每族 × 每 t 档 25 例 ≈ 500 例,seed 冻结,`sample_ids_sha256` 进 manifest
  (复用 multimodal_eval 的 manifest 纪律;dev/holdout 二八切分同口径)。

## 3. 指标

- `stale_leak_rate`:答案含过时值且无同键现行值的比例(北极星,越低越好);
- `conflict_report_rate`:冲突对被显式报告(双值或"冲突"字样)的比例;
- `update_adoption_rate`:knowledge-update 链回答采用最新 active 值的比例;
- `unknown_honesty_rate`:未知 key 正确弃答比例;
- 全部按 t 档位分桶输出压力曲线;LLM 不参与判分(锚串 + verdict 机械判)。

## 4. 与既有设施的关系

- 判定引擎复用 P2/P3:compile_evidence_pack + verify_answer(verdict/violation 已是机械判);
- 运行器扩展 `run_governance_eval`:新增 scenario generator 模块 + t 档位循环;
- 回答来源两档:①"仅记忆层"(Evidence Pack 直接渲染,考治理层本身)②"端到端"
  (executor + `MASE_EVIDENCE_PACK_INJECTION=1`,考闭环;需真模型,单列 lane 不混分);
- 反过拟合:生成器规则通用,不得引用任何真实评测集锚串;holdout 档冻结后禁逐例看。

## 5. 模块布局

```
benchmarks/staleness_pressure/generate_scenarios.py   【新】确定性场景生成(seed 冻结)
benchmarks/staleness_pressure/run_pressure.py         【新】t 档位循环 + 指标聚合 + manifest 校验
benchmarks/staleness_pressure/README.md               口径、基线表、反过拟合政策
src/mase/governance/eval_suite.py                     lane 扩展(staleness_t0/t7/t30/t90)
```

## 6. 验收

- 生成器幂等:同 seed 双跑 sample_ids_sha256 一致;
- 仅记忆层 lane:MASE 治理开启 vs "last-write-wins 无治理"消融对照(同库去掉 trust/conflict
  逻辑的 degraded 模式),压力曲线分离度即治理层的可展示价值;
- 门禁:quality_gate full 全绿;README 基线表 + 证据目录 `E:/MASE-runs/eval_runs/staleness_*`。
