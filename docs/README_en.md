<div align="center">

# MASE
**A dual-whitebox memory engine for LLM agents.**
**88.71% on LV-Eval 256k with a local 7B model.**

> 🚫 **No vector black-boxes.** MASE turns agent memory into an inspectable,
> editable, benchmarked engineering system built around SQLite, Markdown, and
> explicit fact management.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-69%2F69%20passing-brightgreen)
![Concurrency](https://img.shields.io/badge/concurrency-battle--tested-orange)
![NoLiMa-32k](https://img.shields.io/badge/NoLiMa--32k-60.71%25%20(%2B58.9pp)-red)
![LongMemEval](https://img.shields.io/badge/LongMemEval--S-84.8%25-blueviolet)

<a href="../README.md"><b>中文</b></a> | <b>English</b>

![MASE vs baseline on NoLiMa long-context (3-way comparison)](assets/nolima_3way_lineplot.png)

</div>

## What MASE Is

MASE is a **dual-whitebox memory engine for LLM agents**.

It splits agent memory into two controlled surfaces:

- **Event Log** for retrieval and raw conversation history
- **Entity Fact Sheet** for the latest structured facts that can overwrite stale state

## Why Not Black-Box Memory

MASE rejects black-box vector memory as the default answer because:

1. Facts change over time.
2. Memory you cannot inspect is memory you cannot debug.
3. Long-context performance is first a context-governance problem, not just a window-size problem.

## How MASE Works

- **SQLite + FTS5** for raw event-log recall and structured fact storage
- **Markdown / tri-vault** for human-readable auditability and portability
- **Entity Fact Sheet** for fact replacement over fact accumulation
- **Runtime Flow**: Router → Notetaker → Planner → Action → Executor

## Evidence

| Benchmark | Model | MASE | Naked baseline | Δ |
|---|---|---|---|---|
| LV-Eval EN 256k | qwen2.5:7b local | **88.71%** | **4.84%** | **+84pp** |
| NoLiMa ONLYDirect 32k | qwen2.5:7b local, MASE chunked | **60.71%** | **1.79%** | **+58.9pp** |
| LongMemEval-S 500 | GLM-5 + kimi-k2.5 + LLM-judge | **84.8%** | **70.4%** | **+14.4pp** |

## Quick Start

```bash
git clone https://github.com/zbl1998-sdjn/MASE.git
cd MASE
pip install -e ".[dev]"
python -m pytest tests/ -q
python mase_cli.py
```

For deeper reproduction commands, see [BENCHMARKS.md](../BENCHMARKS.md).
For the full demo list, see [examples/README.md](../examples/README.md).

## Integrations

- LangChain `BaseChatMemory`
- LlamaIndex `BaseMemory`
- MCP server
- OpenAI-compatible endpoint

## Limitations

MASE is strongest at fact updates, cross-session memory, and inspectable memory control.
It is not yet the final answer for broad semantic retrieval or high-concurrency server runtime.

## Roadmap

- Whitebox semantic retrieval
- Stronger async / server-grade runtime
- More benchmark triangulation
- More integrations

## Contributing
