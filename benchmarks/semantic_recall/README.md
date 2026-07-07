# semantic_recall — 治理层语义发现的同义改写召回诊断面

**定位**:诊断/校准面(调 threshold/top_n 用),**非冻结 holdout**;真实 bge-m3,
判分机械。对抗性 lane 禁用 `MASE_SEMANTIC_DISCOVERY` 的政策见
`docs/BENCHMARK_ANTI_OVERFIT.md`(Adversarial-Lane Feature Flags)。

**构成**:24 条已治理事实(16 条有配对查询 + 8 条纯噪声池)、16 条零关键词重叠
的中文同义改写查询、8 条完全无关负例查询;同库 A/B(flag off/on)走
`compile_evidence_pack`,统计 Verified 命中/混入/误发现与热缓存延迟。

```bash
python -X utf8 benchmarks/semantic_recall/run_semantic_recall.py
# 参数试验:MASE_SEMANTIC_THRESHOLD=0.5 MASE_SEMANTIC_TOP_N=3 python ...
```

## 2026-07-07 校准记录(bge-m3,run `semantic_recall_20260707T001213Z` 及参数扫描)

基线(flag off):paraphrase_hit **0.0**——关键词 substring 对零重叠改写完全盲区。

| threshold | top_n | paraphrase_hit | extra_noise | negative_false |
|---|---|---|---|---|
| 0.50 | 5(旧默认) | 0.9375 | 0.3125 | 0.25 |
| 0.50 | 1 | 0.9375 | **0.0** | 0.25 |
| **0.55** | **1(现默认)** | **0.75** | **0.0** | **0.0** |
| 0.60 | 1 | 0.5625 | 0.0 | 0.0 |

相似度分布取证(retrieval_runs 审计行):目标最低 0.538(咖啡偏好/VPN 两条),
非目标噪声顶点 0.562(语义近邻:健身房↔会议室、报销工具↔报销上限),
负例顶点 0.514(班车↔地铁站)。

**默认值选择(top_n=1, threshold=0.55)**:
- top_n=1 零代价消噪:目标只要过阈值,几乎总是该查询的语义第一名;
- 0.55 精确优先:对负例顶点留 0.036 边距。0.52–0.53 在本面上可"两全"
  (hit 0.94 + false 0),但那是对 24 条事实贴 0.024 边距调参——分布换个
  事实池就会漂,拒绝过拟合诊断面;
- 失败不对称性:漏掉改写(诚实弃答,可恢复)轻于把无关事实当 Verified 注入
  (答非所问/上下文污染),与"宁缺毋滥"哲学一致;
- 高召回场景(交互式助手、用户可容忍多给)自行设 `MASE_SEMANTIC_THRESHOLD=0.5`。

延迟(热缓存):~0.73–0.77s/查询(含 1 次查询向量 embed);flag off 0.007s。

## 已知边界(诚实)

- 16/8 的查询规模只够定方向与粗校准,边距(0.514 vs 0.538)极窄,
  不同领域/规模的事实池必须重校准后再改默认;
- 改写查询为人工撰写,与真实用户措辞分布有差距;
- 本面只测治理层 facts 检索,与长上下文事件检索(NoLiMa 面)无关。
