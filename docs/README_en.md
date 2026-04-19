# MASE 2.0 (English) — WIP

> **Status: Translation in progress.** The authoritative README right now is the [Chinese version](../README.md).
> A geek-tone English translation is tracked in the project todos and will land before the public-release flip.

## TL;DR (read this much for now)

- **What it is**: Memory-Augmented Smart Entity 2.0 — a schema-less SQLite + per-day Markdown
  dual-whitebox memory layer for LLM agents. No vector DB, no embeddings, no rebuild step.
- **Why it matters**: Lifts a local 7B model (`qwen2.5:7b`) from **1.79%** to **60.71%** on
  NoLiMa ONLYDirect 32k (+58.9pp), 88.71% on LV-Eval EN 256k, 84.8% on LongMemEval-S 500.
- **How**: chunked retrieval → BM25/FTS5 recall → notetaker fact-sheet upsert → executor LLM.
  Every step is inspectable with `sqlite3` or any Markdown editor.
- **Concurrency**: Round-2 audit cleared. SQLite handle leaks fixed (`contextlib.closing` + WAL),
  tri-vault uuid temp files + per-target locks + 3-retry `os.replace` on Windows, GC daemon
  threads drained at `atexit` (≤8s cap), `os.environ.setdefault` to prevent cross-thread pollution.
  69/69 unit tests passing.

## Quick Start

```bash
git clone https://github.com/zbl1998-sdjn/MASE-demo.git
cd MASE-demo
pip install -e ".[dev]"
cp .env.example .env
python -m pytest tests/ -q
```

## Anti-RAG Manifesto

> The best AI memory isn't a black-box of floating-point vectors —
> it's structured facts you can `UPDATE` at 3 AM.

Vector DB + RAG is the consensus stack, but it fails three real-world scenarios:
1. **Temporal conflicts**: yesterday "I don't eat cilantro" vs today "actually I tried it, it's fine" —
   vector recall returns both, small models hallucinate.
2. **Black-box opacity**: when the AI mis-remembers your preference, you can't `UPDATE` a 1536-dim float.
3. **Lexical islands**: small phrasing shifts kill recall in embedding space.

MASE picks the most contrarian-yet-effective stack: **SQLite + Markdown**. White-box. Editable. Atomic.

---

For the full architecture, benchmarks, ecosystem integrations, env-gates,
and contributing guide, please refer to the [Chinese README](../README.md) until
the full English translation lands.
