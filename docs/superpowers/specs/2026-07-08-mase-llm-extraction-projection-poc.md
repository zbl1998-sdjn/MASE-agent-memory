# MASE LLM 抽取投影 POC 设计(knowledge-update 靶向)

- 状态:POC 实施中(2026-07-08)
- 日期:2026-07-08
- 靶:LongMemEval-S **knowledge-update 78 例子集**(judge 复评实证:本地 53.8% vs
  4 月云端 88.5%,-34.7pp,是本地 lane 唯一结构性坍塌;temporal 65.4 本地=云端,
  证明它是任务难度非架构缺失,不在本 POC 射程)
- 上游:事件→事实投影切片①②(管道全通,缺自然语言抽取器);Evidence Pack 注入
  (`MASE_EVIDENCE_PACK_INJECTION`,engine.py 已接);多模态 doc_facts 抽取纪律
- 前置证据:kv_extract 对对话零信号(1.8% 结构、伪命中 13.6%,已实证);
  judge 复评把靶从推测变定论

---

## 1. 假设(一句话,可证伪)

对 knowledge-update 会话轮做 LLM 事实抽取 → 治理层 supersede 给出**现行值** →
Evidence Pack 注入让 executor 面对预消化的 Verified 值而非 30 行原文 →
knowledge-update 判分显著上升(判定:judge ≥ +8pp 且无越界幻觉)。

## 2. POC 范围(最小可证伪,不做全量)

| 决策点 | 选定 | 依据 |
|---|---|---|
| 抽取模型 | DeepSeek(`deepseek-chat`,anthropic 兼容端点,key 在位) | 用户选定;与 judge 同源闭环干净;78 例成本 < $1 |
| 抽取契约 | 复用 doc_facts 管道行契约(`category|key|value|evidence`,值逐字,负例零产出) | 多模态轮次实证的抗幻觉格式;不重造轮子 |
| 抽取面 | 仅 knowledge-update 78 案例的 user 会话轮 | POC 靶向;成功后再谈泛化 |
| 幻觉护栏 | value 必须逐字回定 evidence 原文(治理层 span 天然强制)+ 抽取产物人工抽检 20 例 | "读一次记文本"同款;越界即隔离不入 active |
| 答题路径 | `MASE_EVIDENCE_PACK_INJECTION=1` + 治理双写开 | P3 埋的开关首次实战 |
| 对照 | 同 78 例,基线 46.2%(substring)/53.8%(judge)vs POC 两口径 | 单变量,A/B |
| 落地形态 | 一次性 POC 脚本(scratchpad),**不进仓库主链**;证明价值后才谈产品化 spec | 先证可行再工程化 |

## 3. 执行步骤

1. 抽取器薄封装:DeepSeek + doc_facts 系统提示,对话轮 → 管道行事实;
2. 78 案例逐个:建隔离库 → 投影 user 轮事实(经 facade,supersede 生效)→
   `MASE_EVIDENCE_PACK_INJECTION=1` 跑该案例问题 → 记答案;
3. 抽检 20 例抽取产物:幻觉率、knowledge-update 现行值是否被正确 supersede;
4. judge 复评 POC 答案(DeepSeek,同基线口径);
5. 对照裁决 + 无论正负入 DECISIONS(第 N 段)。

## 4. 诚实风险(预声明)

- **抽取幻觉**:LLM 抽出原文没有的值 → 治理层 span 定位失败会拦(降级隔离),
  但漏抽(该抽没抽)无兜底 → 弃答依旧,POC 可能证明"抽取覆盖不足";
- **注入路径首次实战**:`MASE_EVIDENCE_PACK_INJECTION` 有特征测试钉默认行为,
  但 LME 全链首次走它,可能暴露集成问题(best-effort 回退已在 engine.py);
- **成本/延迟**:POC 不计生产延迟;若正,产品化要异步抽取(独立工程);
- **过拟合红线**:78 例是靶不是调参面;抽取契约通用,不得引入 knowledge-update
  题面特征。POC 若正,泛化验证换全量 500 面。

## 5. 验收

- POC 脚本产出对照表(substring/judge × 基线/POC × knowledge-update);
- 抽检报告(20 例抽取幻觉率、supersede 正确性);
- judge ≥ +8pp 且抽检幻觉率 < 10% → 判定假设成立,立产品化 spec;
- 否则 → 负结果入 DECISIONS,记录"抽取覆盖/质量"的实测瓶颈。
