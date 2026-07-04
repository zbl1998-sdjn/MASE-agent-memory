<div align="center">

# MASE

**Dual-whitebox memory for LLM agents.**

> Make agent memory readable, editable, auditable, and testable before sending it back into the model context.

[![CI](https://github.com/zbl1998-sdjn/MASE-agent-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/zbl1998-sdjn/MASE-agent-memory/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-855%20passing-brightgreen)
![Concurrency](https://img.shields.io/badge/concurrency-battle--tested-orange)
![Crash-safe](https://img.shields.io/badge/storage-crash--safe-success)
![LV-Eval](https://img.shields.io/badge/LV--Eval--256k-88.71%25-red)
![NoLiMa-32k](https://img.shields.io/badge/NoLiMa--32k-60.71%25%20(%2B58.9pp)-red)
![LongMemEval-S](https://img.shields.io/badge/LongMemEval--S-61.0%25%20official%20%7C%2080.2%25%20judge-blueviolet)
![Governance](https://img.shields.io/badge/governance-Fact%20Contract%20%E2%86%92%20Claim%20Verifier-8A2BE2)
![Multimodal](https://img.shields.io/badge/multimodal-image%20%7C%20pdf%20%7C%20audio-informational)

<b>中文</b> | <a href="docs/README_en.md">English</a>

![MASE vs baseline on NoLiMa long-context](docs/assets/nolima_3way_lineplot.png)

</div>

## What is MASE?

MASE is a **dual-whitebox memory engine** for LLM agents.

Most agent memory systems start with an opaque vector store: write everything, embed everything, retrieve top-k chunks, and hope the model resolves conflicts. MASE takes the opposite path:

1. **Govern memory first.**
2. **Keep the minimum necessary facts.**
3. **Expose memory in forms humans and tests can inspect.**
4. **Only then inject memory into the model context.**

MASE splits agent memory into two controllable layers:

| Layer | Purpose |
| --- | --- |
| **Event Log** | Append-only conversational and operational history for recall, replay, and audit. |
| **Entity Fact Sheet** | Current structured facts where newer facts can override stale or conflicting ones. |
| **Markdown / tri-vault** | Human-readable memory externalization for review, migration, and debugging. |

On top of these two layers sits a **governance layer** (`src/mase/governance/`) that turns every long-lived fact into a provable object instead of an opaque row: a structured **Fact Contract** with mechanically-verified evidence spans, an **Admission Gate** that blocks secrets/PII/malformed claims before they ever reach `active`, a trust-ladder **Conflict Resolver** that refuses to silently overwrite higher-trust facts, an **Evidence Pack Compiler** that turns retrieval into an explainable, replayable context bundle, and an **Answer Claim Verifier** that checks a generated answer sentence-by-sentence against that pack and flags — rather than hides — unsupported or conflicting claims. See [Memory Governance Layer](#memory-governance-layer) below.

Enterprise documents, images, and audio are supported through a **"read once, remember text" multimodal pipeline** (`src/mase/multimodal/`): a local vision/ASR model transcribes faithfully, a text LLM extracts facts from that transcript, and every fact keeps a byte-level provenance chain back to the original file. See [Multimodal Ingestion](#multimodal-ingestion) below.

The goal is not to replace semantic search everywhere. The goal is to make long-lived agent memory **observable and correctable**.

## Why it matters

Long-context models do not remove the need for memory governance. If an agent remembers stale preferences, contradictory facts, or unsafe file state, a larger context window only makes the failure harder to debug.

MASE focuses on problems that show up in real agent systems:

- facts change over time;
- user preferences conflict with old sessions;
- agents need cross-session continuity;
- a crash or machine reboot must not wipe persisted memory (SQLite WAL keeps committed facts durable; see `examples/09_resume_after_crash`, `10_persistent_chat_cli`);
- memory writes must be reviewable;
- recall should explain why something was selected;
- tests should verify memory behavior without relying on a black box.

In short:

> MASE turns agent memory from "hidden retrieval magic" into an engineering surface.

## Architecture

```text
User / Agent Runtime
        |
        v
Router -> Notetaker -> Planner -> Action -> Executor
        |             |            |
        v             v            v
 SQLite + FTS5   Entity Facts   Markdown / tri-vault
        |
        v
Bounded recall context for the LLM

Multimodal file (image / PDF / audio)
        |
        v
Vision/ASR transcript -> Fact extractor -> Governance layer -> Evidence Pack -> Claim Verifier
                                                |
                                    facts / evidence_spans / fact_edges / review_actions
```

Core ideas:

- **SQLite + FTS5** for deterministic, portable event and fact search.
- **Entity Fact Sheet** for update-aware memory instead of endless fact accumulation.
- **Markdown / tri-vault** for readable memory artifacts.
- **Hybrid recall** for combining keyword signals, structured facts, and LLM-assisted filtering.
- **Governance layer** for provable facts: Fact Contract, Admission Gate, Conflict Resolver, Evidence Pack, Claim Verifier (all additive tables, zero changes to the legacy read path).
- **Multimodal ingestion** for images/PDF/audio with byte-level provenance chains, engine-agnostic (local Ollama VLM/ASR today).
- **Compatibility surfaces** for LangChain, LlamaIndex, MCP, and OpenAI-compatible endpoints.

## Memory Governance Layer

Most memory systems let anything become a "fact." MASE's governance layer (`src/mase/governance/`, additive on top of `facts` / `evidence_spans` / `fact_edges` / `review_actions` tables) makes that mechanically hard to do wrong:

```text
candidate claim
  -> Admission Gate (G2 structurable / G3 secret&PII / G5 TTL)
  -> Evidence Binder (mechanical substring location in the source text)
  -> Conflict Resolver (trust-ladder: lower-trust claims never silently overwrite higher-trust active facts)
  -> active | quarantined | rejected  (never "active" without a located evidence span — enforced, not advisory)
```

- **Fact Contract + Evidence Span**: every fact carries `subject/predicate/object`, a trust level (E0–E5), and a span that must resolve back into the source text's exact characters (`sha256` over the matched substring). A fact with no located evidence cannot become `active` through any code path — this is tested, not just documented.
- **Admission Gate**: secrets/API keys/private keys are rejected and redacted before they ever touch storage; PII is quarantined for human review; malformed claims never reach `active`.
- **Conflict Resolver**: same-key updates use a trust ladder, not "last write wins" — a low-trust inference can never silently overwrite a user's direct statement; conflicting facts are linked with an explicit `conflicts_with` edge instead of one disappearing.
- **Evidence Pack Compiler** (`scripts/inspect_recall.py`): recall is compiled into a structured, explainable bundle — Verified Facts (with `why_selected` and a full score breakdown), Conflicts, Unknowns, and Do-Not-Assume — instead of raw text chunks. Every retrieval and every compiled pack is logged and replayable.
- **Answer Claim Verifier**: a generated answer is checked sentence-by-sentence against the Evidence Pack. Sentences that repeat a stale, quarantined, or one-sided-conflicting claim are flagged inline (`revise`) or the whole answer is refused with an explicit "unknown" list instead of fabricating (`refuse`).
- Injecting the Evidence Pack into the executor prompt is opt-in (`MASE_EVIDENCE_PACK_INJECTION=1`); it is off by default so existing benchmark behavior is unchanged until you turn it on.

Design docs and acceptance evidence: `docs/superpowers/specs/2026-07-0[3-4]-mase-governance-p*.md`, `E:/MASE-runs/p{0,1,2,3}_acceptance/`.

## Multimodal Ingestion

Images, PDFs, and audio become governed, traceable facts through a "read once, remember text" pipeline (`src/mase/multimodal/`):

```text
file -> security jail + content-addressed asset store (sha256)
     -> local VLM / ASR transcription (faithful transcript, not fact extraction)
     -> text LLM fact extraction (pipe-delimited contract: category | key | value | evidence)
     -> governed fact (Evidence Span located in the transcript, provenance chain to the original bytes)
```

```bash
python -m mase.multimodal ingest ./docs --mode minicpm   # or default qwen2.5vl:7b
python mase_cli.py ingest ./docs
```

- Engine-agnostic: works with any Ollama-served vision/ASR model; provider-aware image serialization also supports OpenAI/Anthropic-style multimodal messages.
- Every extracted fact resolves back to `media_extraction` (full transcript) → `media_asset` (sha256) → the original file bytes — a complete provenance chain, not a summary.
- Evaluated on `benchmarks/multimodal_eval/` — 266 cases across synthetic, SROIE (real receipts, MIT), XFUND-zh (real Chinese forms, CC BY-NC-SA), and LibriSpeech (real speech, CC BY); official holdout (212 cases, single run, 2026-07-05): **fact_anchor_rate 0.85**, **halluc_ok_rate 1.0**, provenance 1.0. See `benchmarks/multimodal_eval/README.md`.

## Evidence

MASE has been evaluated across long-context and memory-oriented benchmarks:

| Benchmark | Model / Setting | MASE | Baseline | Delta |
| --- | --- | --- | --- | --- |
| LV-Eval EN 256k | qwen2.5:7b local | **88.71%** | **4.84%** | **+84pp** |
| NoLiMa ONLYDirect 32k | qwen2.5:7b local, MASE chunked | **60.71%** | **1.79%** | **+58.9pp** |
| LongMemEval-S 500 | GLM-5 + kimi-k2.5 verifier | **61.0% official substring** / **80.2% LLM-judge** | **70.4% substring** / **72.4% LLM-judge** | **+7.8pp judge** |

LongMemEval is reported with multiple lanes:

- **61.0% (305/500)**: official substring-comparable lane.
- **80.2% (401/500)**: LLM-judge lane from the same iter2 full_500 run.
- **84.8% (424/500)**: post-hoc combined/retry diagnostic, **not** the public headline.

Detailed benchmark notes live in `BENCHMARKS.md` and `docs/benchmark_claims/`.


## 历史最佳成绩 (Best Observed Runs)

> 本节为全产物扫描汇总(`MASE_RUNS_DIR` 下 845 个结果文件),记录每个配置的**单次运行最高分**。
> 头条表(上方 Evidence)取的是保守代表值;本表是历史峰值。口径见末尾「读法」。
> 归档产物与带哈希复现见 `MASE-runs-reproduce/`(`best_runs/`、`BEST_SCORES.md`、`REPRODUCTION_SUMMARY.md`)。

### LV-Eval factrecall — 单次最佳(本地 qwen2.5:7b)

| 切片 | EN 最佳 | ZH 最佳 |
|---|---|---|
| 16k | 99.41% (169/170) | 91.61% (142/155) |
| 32k | 98.26% (169/172) | 92.94% (158/170) |
| 64k | 96.81% (182/188) | 93.06% (161/173) |
| 128k | 97.01% (162/167) | 96.05% (170/177) |
| 256k | **98.39% (122/124)** | **100.00% (174/174)** |

### LongMemEval-S 500 / NoLiMa / LongBench-v2

| Benchmark | 最佳 | 口径 |
|---|---|---|
| LongMemEval substring(best stable 单次) | 75.4% (377/500) | multipass + length-aware |
| LongMemEval substring(头条) | 61.0% (305/500) | 云端 GLM-5 + kimi 链路 |
| LongMemEval LLM-judge(头条) | 80.2% (401/500) | judge 仅 FAIL→PASS |
| NoLiMa ONLYDirect 4k / 8k | 100% (56/56) | 本地 qwen2.5:7b |
| NoLiMa ONLYDirect 16k / 32k | 75.0% / 60.71% | 本地 qwen2.5:7b |
| LongBench-v2 short | 33.33% (10/30) | 7B 推理天花板,与 Llama3.1-8B 官方持平 |

### 当前代码带哈希复现(固化证据)

- LV-Eval EN+ZH 全 10 切片已在本机用当前代码重跑并捕获 `sample_ids_sha256` 真实哈希,见 `MASE-runs-reproduce/lveval_full_sweep_reproduce_*.{json,md}`。
- EN 256k 头条切片:当前代码确定性给 **91.94% (114/124)**(`sample_ids_sha256=be9fef61…`,温度=0,两次跑分一致)。
- 历史峰值 98.39% 来自更早代码版本(早于反过拟合哈希插桩),当前代码无法字面复现——差异为**代码演进**而非运行方差。

### 读法(诚实口径)

- **单次 vs best-of**:上表为单个结果文件内的全量运行峰值。LongMemEval 159 批次「按题去重取 best」可达 89.2% (446/500),但每题最多跑过 25 次,属 post-hoc 拼接,**不作为单次成绩**(与仓库 iter4 84.8% 被标注 `uses_failed_slice_retry:true` 的口径一致)。
- **本地 vs 云端**:LV-Eval / NoLiMa 头条为本地 qwen2.5:7b;LongMemEval 头条依赖云端 GLM-5 + kimi-k2.5(纯本地 full-500 仅 ~20% substring)。
- **集群参与度**:LV-Eval 答题路径仅点亮 router(qwen0.5b)+ executor(qwen7b)两个模型,长文由检索压缩(executor 实读 EN ~2.8k / ZH ~5.5k token),非多模型协同;详见 `MASE-runs-reproduce/cluster_participation_*.md`。


## Quick Start

```bash
git clone https://github.com/zbl1998-sdjn/MASE-agent-memory.git
cd MASE-agent-memory
pip install -e ".[dev]"
python -m pytest tests/ -q
python mase_cli.py
```

For benchmark or long-running local work, keep generated memory stores outside the source checkout:

```bash
export MASE_RUNS_DIR=../MASE-runs
```

On Windows PowerShell:

```powershell
$env:MASE_RUNS_DIR = "..\MASE-runs"
```

## Quality gates

Run these before integration work or pull requests:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy
python -m compileall -q -x "(legacy_archive|run_artifacts|dist|build|\.venv|venv|memory|benchmarks[\\/]external-benchmarks|__pycache__|\.pytest_cache)" .
python scripts/audit_repo_hygiene.py --strict
python scripts/audit_anti_overfit.py --strict
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
git diff --check
```

`python -m mypy` is intentionally gradual. Current strict coverage is limited to `executor.py`, `planner_agent.py`, `router.py`, `model_interface.py`, and `protocol.py`.

## Integrations

MASE exposes several integration surfaces:

- LangChain `BaseChatMemory`
- LlamaIndex `BaseMemory`
- MCP server for Claude Desktop / Cursor-style clients
- OpenAI-compatible endpoint
- FastAPI sidecar for local AI agent platforms

Example with LangChain:

```python
from integrations.langchain.mase_memory import MASEMemory

memory = MASEMemory(thread_id="zbl1998::main", top_k=8)
agent_executor.invoke(
    {"input": "What budget did I mention last time?"},
    config={"memory": memory},
)
```

## Current strengths

MASE is strongest when the task requires:

- updated user or project facts;
- cross-session continuity;
- explainable recall;
- human-readable memory review;
- lightweight local persistence;
- benchmarkable memory behavior;
- sidecar integration with an agent SaaS or local agent runtime.

## Limitations

MASE is still an alpha-stage engineering project. It is not yet a universal retrieval layer.

Known boundaries:

- strong synonym and semantic-generalization recall still needs more work;
- large document-level semantic retrieval is not the primary path yet;
- high-concurrency server-grade deployment requires more runtime hardening;
- benchmark claims should be read with the documented lane definitions;
- the governance layer's claim mapping is substring-based ("verbatim-quote" claims), not semantic — paraphrased or reworded answer claims are not yet detected;
- Evidence Pack injection into the executor prompt is opt-in and off by default; the legacy fact-sheet path is still what benchmarks and the default runtime use;
- governance facts are wired from multimodal ingestion and the `mase2_upsert_fact` facade; conversational notetaker facts are not yet dual-written into the governance tables.

## Roadmap

- ✅ Governance layer: Fact Contract, Admission Gate, Conflict Resolver, Evidence Pack, Claim Verifier (P0–P3, done).
- ✅ Multimodal ingestion for images/PDF/audio with byte-level provenance (S0–S2, done).
- White-box semantic retrieval: still keyword/substring-based; synonym expansion and embedding-assisted candidate discovery remain future work.
- Memory Review UI: human-facing approve/reject/edit/merge over the quarantine queue (governance data model is in place; UI is not built yet).
- Document-level claim memory for large files (page/line-mapped facts beyond current span offsets).
- More server-grade async/runtime hardening.
- Broader benchmark triangulation.
- More integrations across LangChain, LlamaIndex, MCP, OpenAI-compatible APIs, and agent SaaS platforms.

## Architecture boundaries

Stable Core, Compatibility Surface, and Experimental Surface are defined in:

- `docs/ARCHITECTURE_BOUNDARIES.md`
- `docs/BENCHMARK_ANTI_OVERFIT.md`

## Contributing

Issues and pull requests are welcome, especially for:

- new model backend adapters;
- benchmark reruns and independent reports;
- integration examples;
- real-world long-memory failure cases;
- memory governance and audit workflows.

## Citation

```bibtex
@software{mase2026,
  author = {zbl1998-sdjn},
  title = {{MASE}: Memory-Augmented Session Engine — Schema-less SQLite memory for LLM agents},
  year = {2026},
  url = {https://github.com/zbl1998-sdjn/MASE-agent-memory},
  note = {Lifts qwen2.5:7b from 1.79\% to 60.71\% on NoLiMa-32k; 61.0\% official substring / 80.2\% LLM-judge on LongMemEval-S}
}
```

## A note from the developer

MASE started from a simple fear: as AI systems become more powerful, their hidden memory becomes harder to trust.

Instead of treating memory as an invisible vector database, MASE keeps memory small, structured, readable, and correctable. It is built around the belief that reliable agents need transparent memory governance before they need more context.

There is no "single heroic model" here. MASE is a lightweight system where Router, Notetaker, Planner, Action, Executor, SQLite, and Markdown each do a small, inspectable job.

If you believe agent memory should be auditable by default, welcome to MASE.
