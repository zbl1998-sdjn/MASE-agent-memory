# Changelog

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
