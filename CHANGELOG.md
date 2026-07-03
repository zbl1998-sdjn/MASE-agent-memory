# Changelog

## [0.10.0] — 2026-07-04 — 治理层 P1:准入门控、冲突治理与 review 通道

### Added
- **Fact Admission Gate(总纲 §4.3 机械可执行子集)**:propose_fact 写入前全序 G2→G3→G5→G1→G4,无旁路
  - `admission_gate.py` 纯函数:G2 可结构化(三元非空);G3 敏感检测(**secret/token/私钥正则 → rejected 且值脱敏 `[REDACTED:*]` 落库,原值不落任何列**,review_actions 记 `security_redact`;PII 手机号/身份证/邮箱 → quarantined + sensitivity=personal);G5 tool_state 默认 TTL 7 天;G0/G7 策略位默认放行(如实标注,不假装实现)
  - 非 active 终态在 `confidence_basis_json.gate` 留痕(gate/action/reason/pattern)——失败可解释
- **Conflict Resolver(trust 阶梯,总纲 §4.4.2 默认优先级机械化)**:同键不同值才算冲突;新 trust ≥ 旧 → supersede + 版本链 + **旧 fact valid_to 闭合到新 observed_at**;新 trust < 旧 → **不静默覆盖**,新事实 quarantined + `conflicts_with` 显性边
- **TTL 执行**:`expire_due_facts()` 批量迁移 + list_facts/get_fact 惰性过期写回(active 且 valid_to 已过 → expired)
- **人工 review 通道**:`approve_fact`(仅限有已定位 span 的 quarantined——不变式人工也不豁免;裁决冲突时对手自动 superseded)/`reject_fact`/`list_review_queue`(带证据与冲突上下文);动作全部留痕 `review_actions` 表(additive)
- **P1 验收**:门禁全套绿;真实 ingest 过全套新门控回归 PASS(`E:/MASE-runs/p0_acceptance/20260703T195734Z/`,48.7s,2 facts active);测试 766 → 800(+34)

## [0.9.0] — 2026-07-04 — 治理层 P0:Fact Contract 与机械证据绑定

### Added
- **FactContract v1 治理层(白盒治理总纲 P0,最小路径第 1 件)**:每条长期事实成为可证明对象
  - 新子包 `src/mase/governance/`:`fact_contract`(FactStatus/TrustLevel E0-E5/ClaimType + frozen 数据对象,`schema_version=fact_contract.v1`)、`evidence_binder`(机械证据定位:精确 substring → 空白归一化容错映射回原文偏移,不做字符级模糊)、`fact_store`(唯一写入口 + 状态机)
  - schema(additive):`facts`/`evidence_spans`/`fact_evidence`/`fact_edges` 四表;读路径零触碰
  - **不变式(测试钉死 + 真数据复验)**:任何 API 路径都无法产生"active 且无已定位证据"的事实——定位失败/inference 一律 quarantined(证据留痕供 review);同键新事实自动 supersede + fact_edges 版本链可回放;retract 理由留痕
  - 双写接线:多模态 ingest 每条事实 propose(E4/document_claim,entity=`media:<sha12>`,best-effort 失败进 `governance_warnings` 不打断摄取);`mase2_upsert_fact` 增可选 evidence_* 五参数(给齐才双写,旧签名零破坏)
  - `scripts/export_fact_sheets.py`:每 entity 一份 markdown 账本(Active/Superseded/Quarantined 三节,竖线转义,front-matter 带 schema 版本)
- **P0 验收证据(真模型,verdict=PASS)**:`E:/MASE-runs/p0_acceptance/20260703T193123Z/evidence.{json,md}`
  - qwen2.5vl:7b + qwen2.5:14b 真实 ingest 49.7s:2 extractions / 2 facts 全部 active、治理覆盖率 2/2、不变式复验(quote_hash 重算)通过、fact sheet 2 份人工可读检查通过
- 测试 725 → 766(+41:契约/定位/状态机/双写/导出);`src/mase/governance` 纳入 mypy 严格门

## [0.8.0] — 2026-07-03 — 多模态抽取优化轮(P1-P6 + 选型)

### Changed
- **正确率/幻觉双北极星优化(冻结 dev 集同尺八轮取证驱动)**:fact 锚串率 0.329 → 0.537 整跑(加权视觉 ~0.66),halluc_ok 0 → 1.00 四轮整跑稳定,召回 0.84 → 0.94,溯源 1.0,全程 0 infra
  - P1 召回查询变体(千分位/VLM 字符空格伪影,查询侧,审计底稿不改写)
  - P2 视觉两段式(VLM 只转写,文本 LLM 抽事实;vision 抽取器 v2→v4)
  - P3 反装饰契约(口号/栏目标题不是事实;负例幻觉 0→1.0)
  - P4 值逐字原文契约 + 评测集 v1.1(XFUND 未勾选框/段落值错标修正,holdout 前重冻结)
  - P5 畸形回复纠正性重试 + 多实体 key 契约 + 同批同 key 防覆盖(真实数据丢失 bug)
  - P6 **管道行事实契约替代 JSON**(7B 对中英混排密集表单 JSON 生成 7/10 崩溃;行格式更稳更白盒;兼容旧 JSON)+ markdown 表格容忍 + 表单填写项指引
  - **doc_facts 定型 qwen2.5:14b**(三方 A/B:qwen7b 中文表单 0.18 指令跟随墙;deepseek-r1:7b 0.56;14b 0.68 同速)
- 长跑稳定性:内存高压环境用 `MASE_OLLAMA_KEEP_ALIVE=0` + `CUDA_VISIBLE_DEVICES=1`(实证止住任务被杀)
- **holdout 正式基线落章(212 例单次全量,反过拟合口径)**:fulltext 0.9325 / **fact 0.6271** / recall 0.8842 / **halluc_ok 1.0** / provenance 1.0 / char_sim 0.8895;infra 3(环境层);证据 `E:/MASE-runs/eval_runs/multimodal_eval_v1_holdout_20260703T084941Z/`,详见 `benchmarks/multimodal_eval/README.md` 正式基线节

### Added
- 白盒记忆治理总纲落库:`MASE_whitebox_memory_governance_plan.md`(v0.1,后续改进的参考基线)

## [0.7.0] — 2026-07-03 — S2 交互式图像摄取与云视觉序列化

### Added
- **交互式上传(S2)**:ChatPage 贴图/拖放 → `POST /v1/mase/media/upload`(multipart,仅图像/PDF,零 URL 抓取)→ 复用 S0 摄取管线(jail/资产库/调度/溯源/幂等)→ 前端 MediaIngestCard 回显事实/sha256/全文摘录/warnings;后续对话经记忆召回回答
  - 路由防护:internal-key 鉴权 + 只读模式拒写 + 落盘前大小上限 + 同哈希去重回显(`deduplicated:true`)
  - provider 感知图像序列化 `image_message.py`:ollama `images` / openai `image_url` data URI / anthropic 图前文后 blocks;vision agent 换云 provider 纯配置,出网仍受 `MASE_ALLOW_CLOUD_MODELS` 审批
  - 前端:`uploadMedia`(multipart 绕过 JSON 头包装器)+ 卡片摘要纯函数化(贴合仓库无 DOM 测试风格);`python-multipart` 钉入 server extra
- **S2 验收证据(verdict=PASS)**:`E:/MASE-runs/s2_acceptance/20260702T213040Z/evidence.{json,md}`
  - 真起 sidecar + httpx 真传:抽取 10.8s 事实全对(发票号/供应商/总额)、召回命中、溯源到资产字节;chat 诊断回答正确(不判分);云 lane 如实 skipped

## [0.6.0] — 2026-07-03 — S1 语音转写与时间线事实

### Added
- **语音转写(S1)**:录音(wav/mp3/m4a/flac)→ faster-whisper 本地转写 → 带 `[HH:MM:SS]` 时间戳审计底稿 → `speech_facts` agent(qwen2.5:7b)抽取带时间线 evidence 的事实
  - 接缝演化:`MediaExtractor.extract(asset, payload: MediaPayload)`(视觉 pages / 音频 AudioTrack),S0 特征测试断言零改动
  - `audio_transcriber`(确定性 temp=0/beam=5、模型进程内缓存、CUDA 双时点回退 cpu+int8 且 `device_fallback` 如实标注)+ `audio_extractor`(6000 字符按段分块、畸形回复降级仅存转写稿)
  - 调度:混合文件夹按 `supports(media_type)` 自动分派 vision/audio;CLI `--whisper-model`(默认 large-v3,可切 large-v3-turbo)
  - 音频独立大小上限 500MB;可选依赖 extra `[audio]`(faster-whisper)
  - Windows CUDA DLL:自动注册 pip nvidia wheels(add_dll_directory + **前置 PATH**,后者为 ctranslate2 传统 LoadLibrary 所必需,本机实测)
- **S1 验收证据(双 lane 全 GPU,verdict=PASS)**:`E:/MASE-runs/s1_acceptance/20260702T211558Z/evidence.{json,md}`
  - large-v3:11.9s,带时间戳事实 1,锚词召回 2/2,cuda/float16 零降级;large-v3-turbo:5.3s,同判据全过
- **多模态评测集 multimodal_eval_v1(266 例,4 lane,建集先于优化冻结)**:`benchmarks/multimodal_eval/`
  - synthetic 66(溯源/负例/干扰/三档退化)+ SROIE 100(真实扫描小票,MIT)+ XFUND-zh 50(真实中文表单)+ LibriSpeech 50(真实语音);dev 54 / holdout 212,`sample_ids_sha256` 冻结;确定性跑分器无 LLM 评委

## [0.5.0] — 2026-07-03 — S0 多模态摄取地基(文档/图像)

### Added
- **多模态摄取地基(S0)**:企业文档/图像 → 本地 VLM 白盒抽取 → 带溯源事实入库
  - 新子包 `src/mase/multimodal/`:`security`(路径 jail + allowlist)、`document_loader`(图像直通 / PDF 按页栅格化)、`extractor`(MediaExtractor 协议 + 注册表)、`vision_extractor`(Ollama VLM,严格 JSON 抽取契约,畸形输出降级)、`ingest`(批处理编排,逐文件隔离,幂等键 sha256+extractor+version)、`cli`
  - 存储侧:`mase_tools/media/asset_store.py` 内容寻址资产库(sha256 去重、原子写、写 jail);`mase_tools/memory/media_records.py` 溯源表 CRUD
  - schema(additive):新表 `media_asset` / `media_extraction`;`entity_state`、`memory_log` 加 nullable `source_media_id`;修复 entity_state PK 重建迁移丢新列问题(带回归测试)
  - 溯源链:事实 → media_extraction(全文可审计)→ media_asset(sha256)→ 资产库原始字节;full_text 进 memory_log + FTS5 可召回
  - CLI:`python -m mase.multimodal ingest <folder>`、`python mase_cli.py ingest <folder>`(--mode/--force/--allowed-root/--max-mb)
  - 配置:`config.json` 新增 `vision` agent(默认 `qwen2.5vl:7b`,`--mode minicpm` 切 `minicpm-v4.5`);可选依赖 extra `[multimodal]`(pymupdf)
  - 测试:+33 项(单元全部假抽取器,不碰真模型);`src/mase/multimodal` 纳入 mypy 严格门
- **S0 验收证据(真模型双 lane,verdict=PASS)**:`E:/MASE-runs/s0_acceptance/20260702T140935Z/evidence.{json,md}`
  - qwen2.5vl:7b:PNG+2页PDF → 2 extractions / 6 facts,锚词召回 2/2,溯源链完整,59.1s
  - minicpm-v4.5:同样本 → 2 extractions / 4 facts,锚词召回 2/2,溯源链完整,34.4s
- 设计与计划:`docs/superpowers/specs/2026-07-02-mase-multimodal-s0-design.md`、`docs/superpowers/plans/2026-07-02-mase-multimodal-s0.md`

### Fixed
- `model_providers._split_system_messages` 不再把结构化多模态 content blocks 压成 repr 字符串(S2 交互式贴图前置)

## [Unreleased] — 2026-04-19 — Plan A 收口 + ROI 扩展

### Added
- **LongMemEval Plan A 二号意见检索**: kimi-k2.5 retry 模式 + 零回退合并器
  - `scripts/run_lme_iter4_retry.py` / `run_lme_iter4_retry_part2.py` / `combine_iter4_retry.py`
  - config 新增 `grounded_long_memory_retry_kimi` 模式 (`config.lme_glm5.json`)
  - `MASE_LME_RETRY=1` env 强制路由到 retry 模式 (`src/mase/mode_selector.py`)
- **NoLiMa 3-way 对比图** — `docs/NOLIMA_3WAY.md`、`docs/assets/nolima_3way_lineplot.png`、`scripts/plot_nolima_3way.py`
- **Memory Diff CLI** — `python -m mase_tools.cli memory diff [--from REF] [--to REF]`
  - 新模块 `mase_tools/cli/memory_diff.py`、`mase_tools/cli/__main__.py`
  - 文档 `docs/MEMORY_DIFF.md`
- **Tri-vault 真实接入** — `mase_tools/memory/tri_vault.py:mirror_write` 被 `notetaker_agent.py` 在写后调用
  - `MASE_MEMORY_LAYOUT=tri` 启用，写入 `<vault>/{context,sessions,state}/`
  - 测试 `tests/test_tri_vault_wire.py` (3 通过)
- **Hybrid Recall** (BM25 + dense + temporal-aware rerank) — `src/mase/hybrid_recall.py`
  - `MASE_HYBRID_RECALL=1` 启用，权重通过 `MASE_HYBRID_RECALL_WEIGHTS=α,β,γ` 调整
  - 文档 `docs/HYBRID_RECALL.md` + 7 测试通过
- **Adaptive Verification Depth** (skip / single / dual 三档) — `src/mase/adaptive_verify.py`
  - `MASE_ADAPTIVE_VERIFY=1` 启用，阈值 `MASE_VERIFY_SKIP_THRESHOLD` / `MASE_VERIFY_DUAL_THRESHOLD`
  - 文档 `docs/ADAPTIVE_VERIFY.md` + 7 测试通过
- **持久聊天 Demo** — `examples/10_persistent_chat_cli.py` (78 行)
  - `--reset` 重启证明持久化、零幻觉 iron-rule
  - 文档 `examples/README_10.md`

### Changed
- **README LongMemEval 行**: 公开 headline 收口为 **61.0% official substring / 80.2% LLM-judge**
  - 84.8% combined/retry 结果保留为 diagnostic, 不再作为 public headline
  - 明确标注 LongMemEval 不是 MASE 主战场
- **DECISIONS.md / iter3 status block**: 移除 "≥85% 之前不发布" 的承诺，替换为 "84.8% 已发布, 不刷分"
- `examples/README.md`: 索引新增 #10，原 MCP TODO 顺延为 #11

### Engineering Hardening (本轮回顾)
- ✅ SQLite 绝对路径硬编码 → `MASE_DB_PATH` env 解析 (此前批次)
- ✅ SQLite WAL 模式开启，缓解前后台 GC 并发锁 (此前批次)
- ✅ MCP 工具沙盒：路径穿越防护 + 文件大小限制 (此前批次)
- ✅ Schema 迁移异常静默吞没修复 (此前批次)
- ✅ SQLite connection 显式 `closing()` 包裹，杜绝句柄泄漏 (此前批次)
- ✅ Tri-vault 死代码 → 真实接入主链路 (本批次)

### Won't Do (设计哲学一致性)
- ❌ BAMBOO altqa/senhallu/abshallu — 反事实改写与 MASE 忠实事实证据原则冲突，README 已透明披露 (15.0% smoke-test)
- ❌ 强行刷 LongMemEval ≥85% — qid-bucket / post-hoc retry 结果只作为 diagnostic, public headline 采用更保守的双通道数字

### Files Touched (本轮)
```
docs/NOLIMA_3WAY.md            (new)
docs/HYBRID_RECALL.md          (new)
docs/ADAPTIVE_VERIFY.md        (new)
docs/MEMORY_DIFF.md            (new)
docs/assets/nolima_3way_lineplot.png  (new)
src/mase/hybrid_recall.py      (new)
src/mase/adaptive_verify.py    (new)
src/mase/notetaker_agent.py    (mirror_write hook + hybrid recall hook)
src/mase/router.py             (adaptive verify hook)
mase_tools/memory/tri_vault.py (mirror_write impl)
mase_tools/cli/__init__.py     (new)
mase_tools/cli/__main__.py     (new)
mase_tools/cli/memory_diff.py  (new)
examples/10_persistent_chat_cli.py  (new)
examples/README_10.md          (new)
examples/README.md             (index update)
tests/test_tri_vault_wire.py   (new, 3 passed)
tests/test_hybrid_recall.py    (new, 7 passed)
tests/test_adaptive_verify.py  (new, 7 passed)
scripts/plot_nolima_3way.py    (new)
scripts/run_lme_iter4_retry.py (new)
scripts/run_lme_iter4_retry_part2.py  (new)
scripts/combine_iter4_retry.py (new)
config.lme_glm5.json           (added grounded_long_memory_retry_kimi mode)
README.md                      (LongMemEval row + status block)
CHANGELOG.md                   (this file, new)
```

### Test Status
- 17 new tests added, **all passing** (`pytest tests/test_tri_vault_wire.py tests/test_hybrid_recall.py tests/test_adaptive_verify.py` → 17/17 in 0.59s)
- All new modules default OFF — publishable LongMemEval baseline (61.0% official / 80.2% judge) guaranteed unchanged.
