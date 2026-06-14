<div align="center">

# MASE

**Dual-whitebox memory for LLM agents.**

> Make agent memory readable, editable, auditable, and testable before sending it back into the model context.

[![CI](https://github.com/zbl1998-sdjn/MASE-agent-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/zbl1998-sdjn/MASE-agent-memory/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-620%2B%20passing-brightgreen)
![Concurrency](https://img.shields.io/badge/concurrency-battle--tested-orange)
![Crash-safe](https://img.shields.io/badge/storage-crash--safe-success)
![LV-Eval](https://img.shields.io/badge/LV--Eval--256k-88.71%25-red)
![NoLiMa-32k](https://img.shields.io/badge/NoLiMa--32k-60.71%25%20(%2B58.9pp)-red)
![LongMemEval-S](https://img.shields.io/badge/LongMemEval--S-61.0%25%20official%20%7C%2080.2%25%20judge-blueviolet)

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
```

Core ideas:

- **SQLite + FTS5** for deterministic, portable event and fact search.
- **Entity Fact Sheet** for update-aware memory instead of endless fact accumulation.
- **Markdown / tri-vault** for readable memory artifacts.
- **Hybrid recall** for combining keyword signals, structured facts, and LLM-assisted filtering.
- **Compatibility surfaces** for LangChain, LlamaIndex, MCP, and OpenAI-compatible endpoints.

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
- benchmark claims should be read with the documented lane definitions.

## Roadmap

- White-box semantic retrieval with write-time tags, read-time expansion, FTS, and LLM filtering.
- More server-grade async/runtime hardening.
- Broader benchmark triangulation.
- More integrations across LangChain, LlamaIndex, MCP, OpenAI-compatible APIs, and agent SaaS platforms.
- Memory review workflows before long-term fact/procedure writes.

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
