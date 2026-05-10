<div align="center">

# MASE

**Dual-whitebox memory for LLM agents.**

> Make agent memory readable, editable, auditable, and testable before sending it back into the model context.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-383%2F383%20passing-brightgreen)
![Concurrency](https://img.shields.io/badge/concurrency-battle--tested-orange)
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

## Quick start

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
python -m mypy
python -m compileall -q -x "(legacy_archive|run_artifacts|dist|build|\.venv|venv|benchmarks/external-benchmarks|__pycache__|\.pytest_cache)" .
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
  title = {{MASE}: Memory-Augmented Smart Entity — Schema-less SQLite memory for LLM agents},
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
