# MASE 事件→事实投影设计(治理层接通 event log)

- 状态:切片①② 已实现并验收(2026-07-08 同日:①批量投影 `event_projection.py`+`mase2_project_events`,gold set 5 项;②notetaker 实时链接——handler 捕获最近 user 事件 log id 注入 upsert(工具 schema 零改动,显式传参不覆盖,错误绑定经治理层自动降级 INFERENCE 只会更保守),真实闭环验收:事件→active fact,span 逐字定位事件原文)。LLM 抽取 lane、模糊键归并、engine 自动投影为后续
- 日期:2026-07-08
- 上游:白盒治理总纲(facts/supersede/valid_time);企业 Phase 1 的
  `GovernedFactWriteFacade`(候选表 + source_log_id → 事件原文证据绑定,已存在);
  确定性抽取族 `kv_extract`/`structure_facts`(多模态轮四已验证)
- 动机:对话事件(memory_log)从不变成治理 facts——LME 取证实锤 knowledge-update
  语义缺失的结构性根源;本线价值独立于跑分:让聊天记忆获得 supersede/valid_time/
  冲突治理与字节级溯源,是白盒架构自身的补全

---

## 1. 目标(一句话)

把 event log 中的陈述性内容投影为治理 facts:值逐字来自事件原文(span 可定位),
同键新值自动 supersede 旧值,PII/secret 走既有门控,全程候选表留痕、幂等可重跑。

## 2. 现状盘点(2026-07-08 实读)

| 组件 | 状态 |
|---|---|
| `GovernedFactWriteFacade.record_notetaker_fact` | ✅ 已存在:候选表、source_log_id→事件原文、trust 推断(逐字=5)、非逐字→INFERENCE→隔离 |
| `mase2_upsert_fact` 双写 | ✅ 已接(`MASE_ENTERPRISE_MODE`/`MASE_GOVERNANCE_DUAL_WRITE`) |
| notetaker → source_log_id | ❌ 工具 schema 无此参数,活跃对话落的事实=无源 INFERENCE(切片②) |
| 存量事件批量投影 | ❌ 不存在(本切片) |

## 3. 切片①:确定性批量投影(本次)

| 决策点 | 选定 | 依据 |
|---|---|---|
| 抽取器 | 复用 `kv_extract.parse_kv_lines`(含一行多键)——纯确定性,零 LLM | 值逐字保证 span 定位天然通过;LLM 抽取是后续 lane(多模态 doc_facts 同款分层) |
| 事件面 | 仅 `role='user'` 且未 superseded 的 memory_log 行 | 用户陈述才是事实源;assistant 转述是二手(后续可作低 trust lane) |
| 提交通道 | 逐条走 `facade.record_notetaker_fact(source_log_id=…)` | 复用候选留痕/trust 推断/门控/supersede,唯一写入口不变式不破 |
| category | `general_facts` 固定 + key 取 kv 键规范形 | 与 kv_extract 契约一致;分类细化留后续 |
| 幂等 | 双保险:candidates 表按 source_log_id 跳过已投影事件 + propose_fact 既有 (键,值,quote_hash) 去重 | 重跑零副作用 |
| 门面 | `mase2_project_events(limit=None, thread_id=None)` → 计数报告 | scripts/CLI 可驱动;engine 后台任务不做(巩固线同款保守先例) |
| 开关 | 门面显式调用即投影,无隐藏自动路径 | 显式优于隐式;运行时自动投影属切片② |

## 4. 切片②(已交付):运行时事件链接

notetaker 编排层把"本轮 user 事件的 log_id"注入 upsert 调用(工具 schema 不变,
handler 侧注入),活跃对话的事实即刻获得事件级溯源与 trust=verbatim 判定。

## 4.5 切片③:LLM 抽取投影(产品化,2026-07-08 立项)

POC 四轮 A/B 验证(knowledge-update judge 53.8→74.4、弃答 13→1,DECISIONS
8ec27915/ea3ccd34)后,把抽取投影升格为产品能力:

| 决策点 | 选定 | 依据 |
|---|---|---|
| 抽取器插拔 | `project_events(extractor='kv'\|'llm')`,默认 'kv'(现状字节不变) | 切片①骨架复用:幂等扫描/候选留痕/门控全不动 |
| 对话契约 | POC 验证过的对话抽取系统提示落进 src(`governance/dialogue_facts.py`) | 四轮 A/B 打底;值逐字红线不动 |
| 抽取模型 | `models.dialogue_facts` agent(config 可配;缺省回落 doc_facts) | doc_facts 先例;本地/云端由 config 决定 |
| 键归并 | `MASE_KEY_MERGE=1` 时投影内做 canonical_key 对齐 | POC 实测:supersede 成链的前提 |
| 调度 | 门面/CLI 显式驱动;engine 自动任务 defer | 切片①/巩固线同款保守先例 |
| 写入延迟 | 写入路径零改动(事件先落库,投影事后批量) | 生产不可加同步秒级延迟 |
| 验收 | 特征测试(fake extractor)+ 真实闭环小样本;LME 端到端为可选 | POC 已证增益,不重复烧 |

## 5. 验收(切片①,全确定性)

- gold set:含 `键:值` 的 user 事件 → 投影出 active facts,span 定位回事件原文,
  provenance=memory_log:<id>;同键后续事件新值 → supersede + 版本链;
  闲聊事件零产出;PII 事件 → quarantined(G3 继承);重跑幂等(候选/facts 零新增);
  assistant 事件不投影。
- 门禁:quick 闸全绿;测试计数如实更新。

## 6. 诚实边界(切片①)

- **键形匹配**:supersede 依赖键短语一致("项目预算: 800" 能顶掉 "项目预算: 500";
  "更新一下——项目预算: 800" 的键是整段前缀,不会归并)——模糊键归并/同义键
  是后续 lane(可复用语义发现);
- 仅确定性 `键:值` 结构可投影;自然语言陈述("我的预算是五百块")需 LLM 抽取 lane;
- assistant 事件与 superseded 事件不投影;category 固定 general_facts。
