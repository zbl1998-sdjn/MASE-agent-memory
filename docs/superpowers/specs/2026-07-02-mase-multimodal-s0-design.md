# MASE 多模态能力 — S0 设计:多模态摄取地基 + 文档/图像抽取

- 状态:草案(待用户审阅)
- 日期:2026-07-02
- 范围:多模态特性的**第一个子项目 S0**。其余子项目(S1 语音 / S2 交互式图像+前端上传 / S3 视频 / S4 多模态召回与评测)各自独立走"设计→计划→实现"闭环,本文件不覆盖其实现细节。

---

## 1. 背景与目标

MASE 是"双白盒记忆引擎":先治理记忆、只留必要事实、以人和测试可读的形式暴露,再注入模型上下文;刻意走与不透明向量库相反的路。

多模态需求(图片/语音/视频 + 企业资料)在工程上是 4–5 个独立子系统,超出单个 spec 粒度,因此分解并优先落地 S0。

**S0 目标(一句话)**:把企业文档/图像(png/jpg/截图/PDF)经**确定性、可复核**的 VLM 抽取,变成人和测试都能读的**全文文本 + 结构化事实**,进入现有白盒记忆管线;原始媒体按内容哈希留存做溯源锚点。

**北极星(不黑盒)**:进入记忆的是"看得懂的抽取物 + 完整溯源链",不是不透明向量。每条多模态事实都能沿链回到:抽取记录(含全文)→ 原始资产哈希 → 原始字节。

---

## 2. 已锁定决策(用户确认)

| 决策点 | 选定 | 含义 |
|---|---|---|
| 核心架构 | **方案 A:看一次·记文字** | 原始媒体存资产库做溯源;抽取出的全文+事实进现有 `entity_state`/`memory_log`+FTS5,与文本事实同构 |
| 视觉模型 | **两个都装按配置切换** | 默认 `qwen2.5vl:7b`;`mode=minicpm` 切 `minicpm-v:4.5`。抽取器接口保持模型无关 |
| 文档格式 | **图像 + PDF** | png/jpg/webp/gif/截图 + PDF(PyMuPDF 按页栅格化,无系统级 poppler 依赖) |
| 写入策略 | **自动写入 + 溯源 + 可纠正** | 每条事实带 media 溯源写入;原始抽取文本留存可审计;可用现有纠正工具改 |
| 入口形态 | **CLI/库批处理先做** | 读本地文件夹,走路径 jail,安全面最小;HTTP 上传留到 S2 |
| 推理后端 | **保持 Ollama,抽取器引擎无关** | S0 用 Ollama;抽取器对 `model_interface` 传引擎无关图像表示,将来切 vLLM 为部署级换后端,不重写 S0 |

---

## 3. 子项目分解(全景,供排期)

| # | 子项目 | 产出 | 依赖 |
|---|---|---|---|
| **S0** | 摄取地基 + 文档/图像抽取(本文件) | 资产库、溯源表、抽取器接口、安全边界、CLI 批处理、本地 VLM 抽取入库 | 无 |
| S1 | 语音转写 | 录音 → 本地 ASR → 带时间线文本事实 | S0 |
| S2 | 交互式图像 + 前端上传 | Chat 贴图 → 事实;provider 层 OpenAI/Anthropic 传图;HTTP 上传安全边界 | S0 |
| S3 | 视频理解 | 关键帧抽样 + 音轨 → 摘要事实 | S0+S1+S2 |
| S4 | 多模态召回与反过拟合评测 | 跨模态事实召回口径 + 合规评测集 | S0–S3 |

---

## 4. 架构与模块布局

遵循现有分层与依赖方向:`integrations`(surface)→ `src/mase`(engine)→ `mase_tools`(storage)。S0 不反向依赖、不新建上帝类。

```
入口层
  mase_cli.py                       扩 `ingest` 子命令(薄封装,委托 ingest.py)

引擎层  src/mase/multimodal/         新子包,单一职责/文件
  security.py                       路径 jail(realpath 归一、拒绝符号链接逃逸)+ 类型/大小 allowlist
  document_loader.py                文件 → list[PageImage];PDF→PyMuPDF 按页栅格化;图像直通;缺依赖给明确报错
  extractor.py                      MediaExtractor 协议 + ExtractionResult/CandidateFact(frozen)+ 抽取器注册表(仿 agent_registry)
  vision_extractor.py               VLM 抽取器:引擎无关图像消息 → model_interface.chat("vision", mode=…) → 解析为 ExtractionResult
  ingest.py                         批处理编排:文件夹 → 逐文件隔离管线 → 写事实(带溯源)

存储层
  mase_tools/media/asset_store.py       内容寻址 blob 库:sha256 → <runs>/media_assets/<ab>/<sha256>.<ext>,写路径 jail,按 hash 去重
  mase_tools/memory/media_records.py    新表 CRUD(register_media_asset / get_media_asset / record_extraction / get_provenance_chain …)
  mase_tools/memory/db_core.py          仅加 DDL:media_asset、media_extraction 表;entity_state、memory_log 加 nullable source_media_id(additive ALTER)
  mase_tools/memory/api.py              扩 mase2_* 门面:新增 mase2_register_media_asset / mase2_record_extraction / mase2_get_media_provenance;
                                        既有 mase2_write_interaction、mase2_upsert_fact 增加可选 source_media_id 参数(底层 add_event_log/upsert_entity_fact 同步接受并落列)

配置
  config.json                       新增 "vision" agent:provider=ollama、model_name=qwen2.5vl:7b;modes.minicpm.model_name=minicpm-v:4.5

依赖
  pyproject.toml                    新增 optional extra [multimodal] = ["pymupdf>=1.24,<2.0"]
```

**关键边界:`MediaExtractor` 协议**是整个多模态特性的可插拔接缝,S1–S3 每个模态是接口后的插件:

```python
class MediaExtractor(Protocol):
    name: str
    version: str
    def supports(self, media_type: str) -> bool: ...
    def extract(self, asset: MediaAsset, pages: list[PageImage]) -> ExtractionResult: ...
```

```python
@dataclass(frozen=True)
class CandidateFact:
    category: str
    key: str
    value: str
    confidence: float          # 0..1,尽力值(模型自报或启发式),非标定概率,不得当作可信度阈值硬用
    evidence: str              # 取自全文/页码的证据片段 → 白盒可核对

@dataclass(frozen=True)
class ExtractionResult:
    full_text: str             # 可审计全文(OCR/转写等价物)
    candidate_facts: list[CandidateFact]
    extractor_name: str
    model_name: str
    extractor_version: str
    warnings: list[str]
```

`ExtractionResult` 是**可检视产物**:人和测试直接读 `full_text` 与 `candidate_facts`,无需读模型内部。

---

## 5. 数据模型与 schema(additive,非破坏)

新增 DDL 加入 `db_core._ensure_schema`(schema 单一集中地);列迁移沿用现有 `ALTER TABLE ... ADD COLUMN` 幂等模式;多租户 scoping 列与既有表一致。

```sql
CREATE TABLE IF NOT EXISTS media_asset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL,
    source_uri TEXT,                 -- 原始来源路径(登记时的相对/绝对定位)
    media_type TEXT NOT NULL,        -- image/png | application/pdf | ...
    byte_size INTEGER,
    page_count INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    tenant_id TEXT NOT NULL DEFAULT '',
    workspace_id TEXT NOT NULL DEFAULT '',
    UNIQUE (sha256, tenant_id, workspace_id)   -- 内容寻址去重
);

CREATE TABLE IF NOT EXISTS media_extraction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL,       -- FK → media_asset.id
    extractor_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    full_text TEXT,                  -- 可审计全文
    result_json TEXT,                -- 序列化 ExtractionResult(含 candidate_facts + warnings)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    tenant_id TEXT NOT NULL DEFAULT '',
    workspace_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_media_extraction_media ON media_extraction(media_id, created_at DESC);

-- 既有表加 nullable 溯源列(不影响纯文本路径)
ALTER TABLE entity_state ADD COLUMN source_media_id INTEGER;   -- 幂等:先探 PRAGMA table_info
ALTER TABLE memory_log  ADD COLUMN source_media_id INTEGER;
```

**溯源链(白盒硬保证)**:
```
entity_state.source_media_id ─▶ media_extraction.full_text/result_json ─▶ media_asset.sha256/source_uri ─▶ asset_store 原始字节
memory_log(full_text 行, FTS5 索引)  ← 召回可命中
tri-vault 镜像(现有)                 ← 事实写入落磁盘可审计
```

---

## 6. 数据流(S0 批处理)

```
ingest(folder, allowed_root, mode=None):
  for file in folder:
    1. security.assert_within_jail(file, allowed_root)      # 逃逸 → 跳过+log
    2. media_type = security.classify(file)                 # 非 allowlist → 跳过+warn
    3. sha256, stored_path = asset_store.register(bytes)    # 已存在同 hash → 复用,不重存
    4. media_id = mase2_register_media_asset(sha256, source_uri, media_type, size, page_count)
       # 若该 media_id 已有 same extractor_version 的 extraction → 跳过(幂等),除非 --force
    5. pages = document_loader.load(file)                   # PDF→N页图;图像→1页;损坏→跳过+warn
    6. result = extractor.extract(asset, pages)             # VLM(Ollama, mode 选模型);失败→infra_error 记录,继续下一文件
    7. ext_id = mase2_record_extraction(media_id, result)   # 落 media_extraction(full_text + result_json)
    8. mase2_write_interaction(thread_id="ingest::<sha>", role="system", content=result.full_text,
                               source_media_id=media_id)     # full_text 进 memory_log + FTS5
    9. for f in result.candidate_facts:                     # 自动写入 + 溯源
         mase2_upsert_fact(f.category, f.key, f.value,
                           reason=f"media_extraction:{sha256}", source_media_id=media_id)
    # tri-vault 镜像(现有)在 upsert/write 成功后自动落磁盘
  return IngestReport(processed, skipped, infra_errors, facts_written)
```

逐文件隔离:任一文件抛错落 `infra_errors` 并继续,不打断整批(对齐 `benchmarks/runner.py` 的 attempt_rows/infra_error 模式)。

---

## 7. 模型集成(Ollama,引擎无关)

- 新增 `"vision"` agent 配置,`provider=ollama`。`vision_extractor` 构造引擎无关图像表示,内部序列化器映射到 Ollama chat 的 message 级 `images:[base64]` 兄弟字段(已核实:官方 `docs/api.md`,base64 裸串)。
- 双模型:默认 `qwen2.5vl:7b`;调用 `model_interface.chat("vision", mode="minicpm")` 经现有 mode 机制切 `minicpm-v:4.5`——无需新增切换代码。
- 云策略无碍:Ollama 属本地 provider,不触发 `_enforce_cloud_model_policy`。
- **引擎无关接缝**:序列化器把内部图像表示 → Ollama `images`(S0 唯一后端)。S2 扩展同一接缝到 OpenAI `image_url` / Anthropic `image` block;将来 vLLM 走现有 `openai` provider + localhost base_url(另需一处"localhost 的 openai 视为本地"的小策略调整,属 S2/部署级,不在 S0)。
- **与既有修复的关系(诚实)**:`_split_system_messages` 的多模态透传修复 **S0 不依赖**(Ollama 不走 content block);它是 **S2** 前置。该修复仍应作为独立 `fix:` 先行提交(一特性一提交)。

---

## 8. 安全边界(遵循 CLAUDE.md:新文件/新路由走安全边界,并自查绕过)

- **读**:批处理仅从显式 `allowed_root` 读取;`security.assert_within_jail` 对 realpath 归一后断言在根内,拒绝符号链接逃逸与 `..` 穿越。
- **写**:asset_store 仅写 `MASE_RUNS_DIR/media_assets` 之下(路径 jail)。
- **无网络取图**:S0 不做 URL 抓取,无 SSRF 面。仅本地文件 + base64。
- **类型/大小 allowlist**:仅 `png/jpg/jpeg/webp/gif/pdf`;超限大小拒绝。
- **无 HTTP 上传路由**:S0 不开(留 S2)。
- **自查**:实现后核对是否存在 jail 绕过、是否有路径拼接未归一、是否有把 `source_uri` 当可信路径再打开的二次读取。

---

## 9. 错误处理

| 情形 | 处理 |
|---|---|
| 路径逃逸/越界 | 跳过该文件 + 结构化 log,不入库 |
| 非 allowlist 类型/超大 | 跳过 + warning |
| PDF 损坏/某页栅格化失败 | 跳过该页或该文件 + warning,不崩批 |
| 缺 PyMuPDF 而遇 PDF | 明确报错提示 `pip install "mase-memory[multimodal]"` |
| VLM 调用失败 | 记 `infra_error`,继续下一文件(不抛穿) |
| 同 sha256 已抽取(同 extractor_version) | 幂等跳过;`--force` 才重抽 |

---

## 10. 测试策略(TDD,先行为后实现)

**单元(默认套件,不碰真模型)**:
- `asset_store`:哈希稳定性、去重(同内容→同路径不重存)、路径 jail 逃逸被拒。
- `document_loader`:图像→1 页;构造微型 PDF→N 页;缺 PyMuPDF→明确报错。
- `security`:allowlist 命中/拒绝;`..`/符号链接逃逸拒绝。
- `ingest` 全管线用**假 MediaExtractor**(确定性,无模型):断言事实以正确 `source_media_id` 写入、`full_text` 进 FTS 可搜、溯源链 `mase2_get_media_provenance` 可查、逐文件隔离(注入一个抛错文件不影响其余)。
- schema 迁移:打开旧库 → 断言新表/新列出现且旧行不变。

**验收(integration/slow,真模型,不进默认套件)**:
- 真实 `ollama pull qwen2.5vl:7b` **和** `minicpm-v:4.5`。
- 对小样本(截图 + 扫描件 + 1 个 PDF)分别用两模型各跑一遍批处理。
- 断言:两条模型路径均产出 media_extraction 记录 + 带溯源的事实;full_text 可召回。
- **产出证据文件**落 `MASE-runs`(源码树外),记录 sample、sha256、模型、facts 数、溯源链抽样。

---

## 11. 依赖与验收门

- 新增可选依赖:`pymupdf`(extra `[multimodal]`);核心安装不变。
- 视觉模型:经 Ollama 拉取,非 Python 依赖。
- 质量门:本仓库无 `scripts/quality_gate.py`;声明门禁为 README 手动集(`pytest` / `ruff` / `mypy` / `compileall` / `audit_repo_hygiene.py` / `audit_anti_overfit.py` / 前端)。**S0 验收 = 该套全绿 + 第 10 节真模型证据文件**。缺证据只标"待验收",不标完成。

---

## 12. 显式非目标(YAGNI)

HTTP 上传路由与前端 UI(S2)、语音(S1)、视频(S3)、向量/感知哈希索引(方案 A 已否决)、跨模态召回调优与多模态评测(S4)。

---

## 13. 风险与开放项

- **抽取质量天花板**:7B 级 VLM 对密集/低质扫描件可能漏读;缓解——`full_text` 全留存可重跑、`confidence` 暴露、支持 `--force` 换模型重抽。诚实口径:不承诺 OCR 精度指标,除非有第 10 节证据。
- **PDF 栅格化 DPI**:默认 DPI 影响可读性与 token 成本;设为可配置,默认取文档 OCR 常用值(实现时定,并在证据中记录)。
- **幂等键**:以 `(sha256, extractor_name, extractor_version)` 判重;抽取器升版本即触发可控重抽。
- **多租户 scoping**:media 表带 `tenant_id/workspace_id`,与既有事实 scoping 对齐,避免跨租户串数据。
