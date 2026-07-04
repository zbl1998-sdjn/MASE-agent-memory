<div align="center">

# MASE
**A dual-whitebox memory engine for LLM agents.**
**88.71% on LV-Eval 256k with a local 7B model.**

> 🔍 **No vector black-box at the core.** Retrieval is driven by SQLite +
> FTS5/BM25 over an inspectable, editable, benchmarked store — not an embedding
> vector database. An optional cross-encoder reranker (bge-reranker, on by
> default, switchable off) refines ordering, but recall itself never depends on
> an opaque vector index.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-855%20passing-brightgreen)
![Concurrency](https://img.shields.io/badge/concurrency-battle--tested-orange)
![NoLiMa-32k](https://img.shields.io/badge/NoLiMa--32k-60.71%25%20(%2B58.9pp)-red)
![LongMemEval](https://img.shields.io/badge/LongMemEval--S-61.0%25%20official%20%7C%2080.2%25%20judge-blueviolet)
![Governance](https://img.shields.io/badge/governance-Fact%20Contract%20%E2%86%92%20Claim%20Verifier-8A2BE2)
![Multimodal](https://img.shields.io/badge/multimodal-image%20%7C%20pdf%20%7C%20audio-informational)

<a href="../README.md"><b>中文</b></a> | <b>English</b>

![MASE vs baseline on NoLiMa long-context (3-way comparison)](assets/nolima_3way_lineplot.png)

</div>

## What MASE Is

MASE is a **dual-whitebox memory engine for LLM agents**.

It splits agent memory into two controlled surfaces:

- **Event Log** for retrieval and raw conversation history
- **Entity Fact Sheet** for the latest structured facts that can overwrite stale state

This means MASE is not primarily trying to stuff more context back into the model. It is trying to clean up conflicting facts first, then pass only the minimum necessary facts into the model.

## Why Not Black-Box Memory

MASE rejects black-box vector memory as the default answer because:

1. Facts change over time.
2. Memory you cannot inspect is memory you cannot debug.
3. Long-context performance is first a context-governance problem, not just a window-size problem.

## How MASE Works

MASE's primary narrative is the memory system, not a runtime feature list.

- **SQLite + FTS5** for raw event-log recall and structured fact storage
- **Markdown / tri-vault** for human-readable auditability and portability
- **Entity Fact Sheet** for fact replacement over fact accumulation
- **Runtime Flow**: Router → Notetaker → Planner → Action → Executor
- **Governance layer** (`src/mase/governance/`): Fact Contract + mechanically-verified Evidence Spans, an Admission Gate that rejects secrets/PII/malformed claims, a trust-ladder Conflict Resolver, an Evidence Pack Compiler, and an Answer Claim Verifier — see [Memory Governance Layer](#memory-governance-layer).
- **Multimodal ingestion** (`src/mase/multimodal/`): images, PDFs, and audio become governed facts with a byte-level provenance chain — see [Multimodal Ingestion](#multimodal-ingestion).

## Memory Governance Layer

Every long-lived fact is a provable object, not an opaque row:

```text
candidate claim
  -> Admission Gate (structurable? secret/PII? TTL?)
  -> Evidence Binder (mechanical substring location in the source text)
  -> Conflict Resolver (trust ladder — low-trust never silently overwrites high-trust)
  -> active | quarantined | rejected   (never "active" without a located evidence span)
```

- A fact cannot become `active` through any code path without a mechanically-located evidence span (`sha256` over the matched source text) — enforced by tests, not just documented.
- Secrets/API keys/private keys are rejected and redacted before storage; PII is quarantined for review.
- Same-key updates use a trust ladder instead of "last write wins"; conflicting facts get an explicit `conflicts_with` edge instead of one silently disappearing.
- Recall compiles into a structured **Evidence Pack** (`scripts/inspect_recall.py`) — Verified Facts with `why_selected` and a score breakdown, Conflicts, Unknowns, Do-Not-Assume — fully logged and replayable.
- A generated answer is checked sentence-by-sentence against the pack; unsupported/stale/one-sided-conflict claims are flagged inline or the answer is refused with an explicit "unknown" list instead of fabricating.
- Injecting the Evidence Pack into the executor prompt is opt-in (`MASE_EVIDENCE_PACK_INJECTION=1`, off by default).

## Multimodal Ingestion

```bash
python -m mase.multimodal ingest ./docs --mode minicpm   # or default qwen2.5vl:7b
```

A local VLM/ASR model transcribes images, PDFs, and audio faithfully; a text LLM then extracts facts from that transcript, each with an evidence span located in the transcript and a provenance chain back to the original file bytes (`media_extraction` → `media_asset` → sha256). Official holdout evaluation (212 real+synthetic cases, single run, 2026-07-04): **fact_anchor_rate 0.72**, **halluc_ok_rate 1.0**. See `benchmarks/multimodal_eval/README.md`.

## Evidence

| Benchmark | Model | MASE | Naked baseline | Δ |
|---|---|---|---|---|
| LV-Eval EN 256k | qwen2.5:7b local | **88.71%** | **4.84%** | **+84pp** |
| NoLiMa ONLYDirect 32k | qwen2.5:7b local, MASE chunked | **60.71%** | **1.79%** | **+58.9pp** |
| LongMemEval-S 500 | GLM-5 + kimi-k2.5 verifier | **61.0% official substring** / **80.2% LLM-judge** | **70.4% substring** / **72.4% LLM-judge** | **+7.8pp judge** |

> LongMemEval reports two scoring lanes (see `docs/benchmark_claims/`):
> - 61.0% (305/500) — official substring-comparable lane
> - 80.2% (401/500) — LLM-judge lane, same iter2 full_500 run
> - 84.8% (424/500) — post-hoc combined/retry diagnostic, **not** the public headline

- MASE is not just able to remember; it can distill facts reliably under long context.
- Architecture, not parameter count, determines whether long context remains usable.
- This is not a concept demo; it is an engineering project shaped by benchmarks and audits.

## Quick Start

```bash
git clone https://github.com/zbl1998-sdjn/MASE.git
cd MASE
pip install -e ".[dev]"
python -m pytest tests/ -q
python mase_cli.py
```

If you are just getting started, begin with `python mase_cli.py`.

For deeper reproduction commands, see [BENCHMARKS.md](../BENCHMARKS.md).
For the full demo list, see [examples/README.md](../examples/README.md).

## Integrations

- LangChain `BaseChatMemory`
- LlamaIndex `BaseMemory`
- MCP server
- OpenAI-compatible endpoint

```python
from integrations.langchain.mase_memory import MASEMemory

memory = MASEMemory(thread_id="zbl1998::main", top_k=8)
agent_executor.invoke({"input": "What was my budget again?"}, config={"memory": memory})
```


## Limitations

MASE is currently strongest at fact updates, cross-session memory, consistency control, and whitebox debuggability.

It is not a terminal solution for generic semantic retrieval, especially in these scenarios:

- synonym- and paraphrase-heavy semantic generalization
- large-scale document-level semantic recall
- high-concurrency server runtime (the current main path still favors CLI / benchmark / single-process use)
- the governance layer's claim mapping is substring-based (verbatim quotes), not semantic paraphrase detection
- Evidence Pack injection into the executor is opt-in and off by default; conversational notetaker facts are not yet dual-written into the governance tables (multimodal ingestion and the upsert facade are)


## Roadmap

- ✅ Governance layer: Fact Contract, Admission Gate, Conflict Resolver, Evidence Pack, Claim Verifier (done)
- ✅ Multimodal ingestion for images/PDF/audio with provenance (done)
- Whitebox semantic retrieval (synonym/embedding-assisted candidate discovery)
- Memory Review UI over the quarantine queue
- Stronger async / server-grade runtime
- More benchmark triangulation
- More integrations

## Contributing

MASE welcomes contributions. If you'd like to help, please consider:

- Adding new model backends
- Re-running benchmarks and submitting reproducible results
- Building integrations (LangChain, LlamaIndex, MCP, etc.)
- Reporting real-world long-memory failure cases with reproducible traces

### Citation

```bibtex
@software{mase2026,
  author = {zbl1998-sdjn},
  title = {{MASE}: Memory-Augmented Session Engine — Schema-less SQLite memory for LLM agents},
  year = {2026},
  url = {https://github.com/zbl1998-sdjn/MASE},
  note = {Lifts qwen2.5:7b from 1.79\% to 60.71\% on NoLiMa-32k; 61.0\% official substring / 80.2\% LLM-judge on LongMemEval-S}
}
```

## 💡 A Note from the Developer

Honestly — I'm just a newcomer who picked up large-language-model knowledge **only 3 months ago**.

Along the way I came to a conviction: when people stand in front of an unfathomably powerful **black-box AI**, the **fear they feel often outweighs the wonder**. We're afraid it will quietly rewrite our memories, afraid it will hallucinate in ways we can't trace, and afraid we'll lose control.

That's exactly why MASE walked away from the giant black box and chose **dual-whitebox**. In this system:

> **No "lone-hero" omnipotence — only "many hands, each doing what they do best".**

We don't ask one giant model to do everything. Instead, a 2.72 MB lightweight kernel strings together **Router / Notetaker / Planner / Action / Executor**, letting each small model play to its strengths. Precisely because MASE keeps the architecture this simple, it leaves room for what comes next: multi-agent collaboration, MCP integrations, and a plug-in ecosystem.

**The beauty of open source is that no single person has to be perfect.** If you share the values of transparency, minimalism, and collaboration, welcome to MASE.

— *zbl1998-sdjn, Spring 2026*
