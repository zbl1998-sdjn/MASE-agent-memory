# staleness_pressure_v1 — 时漂压力基准(治理 vs 退化记忆)

**动机**:业界报告(Mem0 2026 基准综述,厂商自报)称记忆系统 benchmark 平均 ~91%
而生产 30 天 staleness 后掉到 55–70%,主因 stale data / 实体矛盾 / 时间建模缺失。
这三样正是 MASE 治理层(supersede + trust ladder + valid_time + conflicts_with)的
设计目标——本基准把该差距做成常设回归面。

**口径**:全机械判分,零 LLM 参与,分数逐位可复现。每 case 独立 SQLite,按场景
回灌事实(observed_at = 运行时刻 − offset_days),`compile_evidence_pack`(P2 白盒
召回+编译)产出证据包后直接对 pack 判分。

## 场景族 × 时间档(t ∈ {0, 7, 30, 90} 天)

| 族 | 构造 | 指标 |
|---|---|---|
| update | 同键 3–6 版知识更新链(链长随 index) | `update_adopted`(只用最新值)/ `stale_leak`(旧值混入 Verified) |
| conflict | 高信任在前 + 低信任在后的同键冲突(信任对随 index) | `conflict_reported`(双值并列显式陈列)/ `stale_leak`(低信任值被当已验证) |
| ttl | tool_state 回灌 t 天前(G5 默认 TTL 7 天) | `ttl_correct`(<7 天在 / ≥7 天必须不在) |
| unknown | 查询从未入库的键 | `unknown_honest`(Unknowns 显式列出而非编造) |

**退化模式(degraded)**:同一批版本以独立 scope 落库、全部保持 active——模拟
"只追加、无更新语义"的黑盒记忆(经典向量库姿态),用于展示治理层的分离度;
覆盖 update 与 conflict 两族。

确定性说明:管线无随机成分,同一配置的结果恒定;`per_family` 增加的是**结构
变体**(链长 3–6、四组信任对),不是统计样本。manifest 哈希只对场景定义计算,
与运行时间无关,同参数双跑必须一致(测试钉死)。

## 运行

```bash
python -X utf8 benchmarks/staleness_pressure/run_pressure.py            # per-family 5,120 例,秒级
python -X utf8 benchmarks/staleness_pressure/run_pressure.py --per-family 2   # 冒烟
```

产物落 `E:/MASE-runs/eval_runs/staleness_pressure_<ts>/results.json`
(scenarios_sha256 + family/mode 与 family/mode/t 两级聚合 + 逐 case 维度)。

## v1 基线(2026-07-07,per-family 5 / 120 例)

| family/mode | 关键指标 |
|---|---|
| update/governed | stale_leak **0.0**,update_adopted **1.0** |
| update/degraded | stale_leak **1.0**,update_adopted 0.0 |
| conflict/governed | conflict_reported **1.0**,stale_leak 0.0 |
| conflict/degraded | conflict_reported 0.0,stale_leak **1.0** |
| ttl/governed | ttl_correct **1.0**(7 天边界两侧全对) |
| unknown/governed | unknown_honest **1.0** |

读法:同一压力面上,治理层全 t 档零 stale 泄漏、全量采用现行值、冲突全部显式
双陈列;"只追加"退化基线 100% 泄漏旧值且零冲突报告——业界生产差距的失败模式
在退化侧被完整复现,在治理侧被机械性消除。证据目录见下方"基线 run"。

- 基线 run:`E:/MASE-runs/eval_runs/staleness_pressure_20260706T192626Z/`(120 例,scenarios_sha256=8d7e5190ed8f255f…)
- 已知边界(诚实):v1 只考"仅记忆层"(证据包本身),端到端(executor +
  `MASE_EVIDENCE_PACK_INJECTION=1`)lane 需真模型,留作 v2;退化基线是护栏拆除
  消融,不代表任何具体第三方产品;update/unknown 两族结果与 t 无关(治理判定
  瞬时生效),t 维度的区分度目前主要由 ttl 族承载。
