<div align="center">

# MASE (Memory-Augmented Smart Entity)
**Schema-less SQLite + per-day Markdown — dual-whitebox memory for LLM agents.**
**Survives 256k adversarial context at 88% with a 7B local model.**

> 🚫 **No vector black-boxes. No memory hallucinations.** A **2.72 MB** minimal kernel built on
> the oldest, most boring tech in the stack — SQLite and Markdown — gives your LLM
> **100% transparent, `UPDATE`-able, bullet-proof "dual-whitebox" persistent memory**.
> No re-indexing. Restart and your agent recalls 30 sessions ago verbatim.
> **An AI memory engine for the real world.**

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-69%2F69%20passing-brightgreen)
![Concurrency](https://img.shields.io/badge/concurrency-battle--tested-orange)
![NoLiMa-32k](https://img.shields.io/badge/NoLiMa--32k-60.71%25%20(%2B58.9pp)-red)
![LongMemEval](https://img.shields.io/badge/LongMemEval--S-84.8%25-blueviolet)

<a href="../README.md"><b>中文</b></a> | <b>English</b>

![MASE vs baseline on NoLiMa long-context (3-way comparison)](assets/nolima_3way_lineplot.png)

</div>

> ### 💡 The Anti-RAG Manifesto
>
> **The best AI memory isn't a black-box of floating-point vectors —
> it's structured facts you can `UPDATE` at 3 AM.**
>
> *— MASE, [read the full manifesto ↓](#-why-rebuild-mase-the-anti-rag-manifesto)*

---

## 📖 Table of Contents

- [✨ Highlights](#-highlights) — Zero-Bloat / Dual-Whitebox / Verified hard numbers
- [🛡️ Battle-Tested concurrency](#️-battle-tested-round-2-audit-cleared)
- [🔌 Integrations](#-integrations) (LangChain · LlamaIndex · MCP · OpenAI-compatible)
- [⚙️ Key env-gates](#️-key-env-gates)
- [⚠️ Why rebuild MASE? (The Anti-RAG Manifesto)](#-why-rebuild-mase-the-anti-rag-manifesto)
- [🛠️ Core architecture](#️-core-architecture)
- [🚀 Quick Start (3 minutes)](#-quick-start)
- [📂 Repo layout](#-repo-layout)
- [🤝 Contributing / Citation / Star History](#-contributing)

---

## ✨ Highlights

> **Built for the real world** where users forget to disable Windows auto-reboot at 1:49 AM.
> MASE doesn't care. The next message recalls memories from 30 sessions ago.
> **Zero re-indexing. Zero embedding pass. Zero warm-up.**

### 🪶 Zero-Bloat Architecture

> No more 500 MB framework spaghetti. MASE tracks at **2.72 MB / 266 files** —
> no bundled vector DB, no heavy ORM, just Python's built-in SQLite FTS5
> plus native data structures. The smallest possible surface area to ship
> **256k extreme context scheduling** and **8-thread concurrency-bullet-proof writes**
> (verifiable: `tests/test_audit_round2_fixes.py::test_tri_vault_concurrent_writes_no_collision`).
>
> **Small, but brutally effective.**

### 🪟 Dual-Whitebox Memory

MASE writes every conversation to two human-readable layers simultaneously:

| Layer | File | Audience | How to intervene |
|---|---|---|---|
| **L1: SQLite + FTS5** | `data/mase_memory.db` | Engineers / agents | Any `SELECT / UPDATE / DELETE` SQL |
| **L2: Markdown audit log** | `memory/logs/YYYY-MM-DD.md` (one file per day, 5 MB rotation) | End users / Obsidian | Open with Notepad / VS Code / Obsidian |

> Want to migrate MASE memory into an Obsidian vault? Just `cp -r memory/logs/` —
> we already speak Obsidian-flavored Markdown.

### 🎯 Verified hard numbers (not marketing — fully reproducible)

| Benchmark | Model | MASE | Naked baseline | Δ |
|---|---|---|---|---|
| 📄 LV-Eval EN 16k fact extraction | qwen2.5:7b local | **97.06%** | (see BENCHMARKS) | — |
| 📄 LV-Eval EN 64k fact extraction | qwen2.5:7b local | **91.49%** | **22.34%** | **+69pp** 📈 |
| 📄 LV-Eval EN 128k fact extraction | qwen2.5:7b local | **83.23%** | **10.78%** | **+72pp** 📈 |
| 📄 LV-Eval EN 256k fact extraction | qwen2.5:7b local | **88.71%** | **4.84%** | **+84pp** 🚀 |
| 🪡 NoLiMa ONLYDirect 32k needle-in-haystack | qwen2.5:7b local, MASE chunked | **60.71%** | **1.79%** (full-haystack) | **+58.9pp** 🔥 |
| 🧠 LongMemEval-S 500 cross-session memory | GLM-4.6 + kimi-k2.5 second-opinion + LLM-judge | **84.8%** (424/500) | 70.4% baseline | **+14.4pp** 📈 |

> **The 32k +58.9pp on NoLiMa is the architectural win.** A naked 7B already loses sight
> of the needle at 32k due to ollama's 8192-token context cutoff. MASE chunked retrieval
> re-feeds the answer-bearing slice back to the model. **No fine-tuning, no model swap.**
> Reproduce: `benchmarks/external-benchmarks/NoLiMa/run_mase_chunked.py` →
> results in `results/external/phase_a_summary.jsonl`.

> **LongMemEval is NOT MASE's main battleground** — that benchmark assumes the entire
> history fits in context, which sidesteps MASE's whole reason for existing.
> MASE's true killer is NoLiMa-32k +58.9pp and the zero-hallucination verifier.
> See ablation report below.

---

## 🛡️ Battle-Tested (Round-2 audit cleared)

Most "memory" libraries look fine in single-thread demos, then deadlock the moment
you put them under concurrent load. MASE refuses toy-grade architecture — it passed
two rounds of deep concurrency audit:

| Hazard | Industry symptom | MASE defense |
|---|---|---|
| **SQLite handle leak** | `database is locked` / `Too many open files` | `contextlib.closing` + WAL across the whole stack |
| **tri-vault write race** | Concurrent `.tmp` collisions corrupt JSON | `uuid4` temp filenames + per-target `threading.Lock` + 3-retry `os.replace` for Windows |
| **Ghost GC daemon** | CLI exits, daemon thread killed mid-LLM-call, memory lost | `MASESystem.join_background_tasks()` + `atexit` graceful drain (≤8s cap) |
| **`os.environ` cross-thread pollution** | Background thread mutates env, main-thread C extension crashes | `os.environ.setdefault` for idempotent writes |
| **Silent schema migration failure** | Old table + new code → cryptic SQL errors at the business layer | `_ensure_schema` raises immediately (no more best-effort) |

**All 69 core unit tests pass** (incl. 7 in `tests/test_orchestrator_audit_fix.py` and 6 in
`tests/test_audit_round2_fixes.py` written specifically for the audit).
Reproduce: `python -m pytest tests/ -q`.

---

## 🔌 Integrations

Drop-in replacements for the usual black-box memory stacks.

- **LangChain `BaseChatMemory`** — one-line replacement for `ConversationBufferMemory`
- **LlamaIndex `BaseMemory`** — plug into LlamaIndex agents
- **MCP server** — Claude Desktop / Cursor connect MASE as their memory layer
- **OpenAI Assistants API compat layer** — zero-change client refactor
- **Cherry Studio / OpenWebUI / NextChat** — works out of the box via OpenAI-compatible endpoint

### ⚡ 3-line LangChain Agent integration

```python
from integrations.langchain.mase_memory import MASEMemory

memory = MASEMemory(thread_id="my-agent::main", top_k=8)
agent_executor.invoke({"input": "What was my budget again?"}, config={"memory": memory})
```

> Real signature: `MASEMemory(memory_key="history", return_messages=True, top_k=8, thread_id="langchain::default")`.
> DB path is resolved via `MASE_DB_PATH` env (default `<project>/data/mase_memory.db`),
> no need to pass it at the call site. See `mase_tools/memory/db_core.py::_resolve_db_path`.

Goodbye `ConversationBufferMemory` token limits. Goodbye `VectorStoreRetrieverMemory` opaque drift.
**Power-cut, reboot, cross-process — the next message still `SELECT`s a fact from 30 sessions ago.**

---

## ⚙️ Key env-gates

| Variable | Default | Purpose |
|---|---|---|
| `MASE_DB_PATH` | `<project>/data/mase_memory.db` | Repoint the SQLite store anywhere — `~/.mase/`, tmpfs in CI, etc. |
| `MASE_MEMORY_LAYOUT` | `legacy` | `tri` enables the entity / sessions / rules tri-vault layout |
| `MASE_MEMORY_VAULT` | `<project>/memory/vault` | Root for the tri-vault on-disk JSON shards |
| `MASE_GC_ENABLED` | `1` | Set `0` to disable async memory garbage collection |
| `MASE_BENCHMARK_FAST_PATH` | `0` | `1` skips Router/Planner LLM calls for benchmark replay |

Full list: see `src/mase/config.py` and the env-gate section in the Chinese README.

---

## ⚠️ Why rebuild MASE? (The Anti-RAG Manifesto)

Every long-context memory stack today reflexively reaches for **vector DB + RAG**.
But once the system runs in a real, long-horizon personal workflow, RAG breaks
in three painful ways:

1. **Temporal conflicts & memory pollution** — yesterday "I don't eat cilantro",
   today "actually I tried it, it's fine". Vector recall returns both, the small
   model splits the difference and hallucinates.
2. **Black-box opacity** — when the AI mis-remembers your core preference, you can't
   `UPDATE` a 1536-dim float vector. Your only lever is to keep repeating yourself
   in chat and hope the embedding gradient drifts.
3. **Lexical islands** — over-reliance on the embedding model's semantic space means
   tiny phrasing shifts kill recall.

**MASE picks the most contrarian-yet-effective stack**: throw away the vector DB,
embrace the oldest and most boring relational engine — **SQLite** — wired to a
**LangGraph** state machine. The result: a 100% transparent, blistering-fast,
physically-editable "white-box AI colleague".

---

## 🛠️ Core architecture

### 1. Extreme white-box memory: SQLite FTS5 + Entity Fact Sheet

MASE memory isn't a tangled JSON blob or a vector shard pile. It's a clean two-layer split:

- **Event log (append-only)** — raw conversation records, indexed by SQLite **FTS5**
  for millisecond BM25 recall. Nothing is ever lost.
- **Entity Fact Sheet** — key-value table maintained via SQL `Upsert` (insert-or-overwrite).
  The user's latest preference / project status overwrites the stale memory atomically.
  The agent only ever reads the freshest facts — turning long-context "comprehension"
  into a one-row `SELECT`.

### 2. Transparent flow engine: LangGraph state machine

No more thousand-line `while` loops or "God classes". The flow is a clean DAG:

`Router` ➡️ `Notetaker (SQLite I/O)` ➡️ `Planner` ➡️ `Action (MCP tools)` ➡️ `Executor`

*Every step's data flow is recorded in `AgentState` — fully observable, easy to debug and extend.*

### 3. Async memory garbage collection

A background `gc_agent.py` daemon periodically pulls unstructured event-log conversations,
asks an LLM to **distill** them into structured JSON facts, and merges them into the
Entity Fact Sheet. The foreground agent only ever consumes the high-signal-to-noise residue.

### 4. Absolute physical control over memory (CLI UI)

The AI is hallucinating? Forgot your real budget?
Just run `python mase_cli.py`. An interactive terminal panel where you `CRUD` the model's
brain like any other database. **You are the system. The model serves you, not the reverse.**

### 5. MCP external tool integration (Model Context Protocol)

MASE isn't just a chat scribe — it's an "AI colleague". Through the native MCP extension
layer it can read local files, get system time, and (in the roadmap) reach into calendars,
send emails, and write the execution outcome back into the memory log.

---

## 🚀 Quick Start

### 0. Clone & install (the boring 60 seconds)

```bash
# 1. Clone
git clone https://github.com/zbl1998-sdjn/MASE-demo.git
cd MASE-demo

# 2. Install (Python 3.10+ recommended, virtualenv strongly suggested)
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env

# 4. Sanity check
python -m pytest tests/ -q
```

### 1. Pull the local models (Ollama)

```bash
ollama pull qwen2.5:7b
ollama pull bge-m3:latest      # BM25 + embedding fallback
```

### 2. Talk to your new white-box colleague

```bash
python mase_cli.py
```

For the LangGraph orchestrator and benchmark scripts, see the corresponding sections in the
[Chinese README](../README.md) — the runtime knobs and the LV-Eval / NoLiMa replay commands
are identical across both languages.

---

## 📂 Repo layout

```
MASE-demo/
├── src/mase/                  # Core engine (modular split, post-God-class)
├── mase_tools/                # Memory subsystem (SQLite + tri-vault + GC + MCP)
├── integrations/              # LangChain / LlamaIndex / MCP server adapters
├── langgraph_orchestrator.py  # LangGraph DAG entry point
├── mase_cli.py                # Interactive memory CRUD console
├── benchmarks/                # MASE-side runners; external benchmark code fetched separately
│   └── external-benchmarks/README.md   ← fetch instructions for NoLiMa/BAMBOO
├── tests/                     # 69 core unit tests, including audit Round-1 & Round-2
├── docs/
│   ├── README_en.md           # this file
│   └── assets/                # benchmark plots used in READMEs
├── examples/                  # 10 self-contained 30-line demos
├── BENCHMARKS.md              # Full reproduction commands + ablation tables
├── DECISIONS.md               # Architecture decision log
├── LEGACY_SHIMS.md            # V1 compatibility surface map
└── RELEASE_NOTES_V2.md        # Release notes for the v2 line
```

---

## 🤝 Contributing

Issues and PRs welcome — especially in these directions:

- **New model backends**: vLLM / llama.cpp / Together / OpenRouter (`src/mase/model_interface.py`)
- **More integrations**: AutoGen / CrewAI / Semantic Kernel
- **New benchmark replays**: BABILong / RULER / ∞Bench adapters (`benchmarks/runner.py`)
- **Bug reports**: long-context recall failures especially welcome — please attach a
  minimal repro plus a `data/mase_memory.db` snippet.

Before opening a PR, please run `python -m ruff check . && python -m pytest tests/ -q`.
CI must be green before merge.

### Citation

If MASE helps your research, please cite:

```bibtex
@software{mase2026,
  author = {zbl1998-sdjn},
  title = {{MASE}: Memory-Augmented Smart Entity — Schema-less SQLite memory for LLM agents},
  year = {2026},
  url = {https://github.com/zbl1998-sdjn/MASE-demo},
  note = {Lifts qwen2.5:7b from 1.79\% to 60.71\% on NoLiMa-32k; 84.8\% on LongMemEval-S}
}
```

### Star History

[![Star History Chart](https://api.star-history.com/svg?repos=zbl1998-sdjn/MASE-demo&type=Date)](https://star-history.com/#zbl1998-sdjn/MASE-demo&Date)

### License

[Apache-2.0](../LICENSE) © 2026 zbl1998-sdjn

---

## 💡 A Note from the Developer

Honestly — I'm just a newcomer who picked up large-language-model knowledge **only 3 months ago**.

Along the way I came to a conviction: when people stand in front of an unfathomably powerful
**black-box AI**, the **fear they feel often outweighs the wonder**. We're afraid it will
quietly rewrite our memories, afraid it will hallucinate in ways we can't trace,
afraid we'll lose control.

That's exactly why MASE walked away from the giant black box and chose **dual-whitebox**.
In this system:

> **No "lone-hero" omnipotence — only "many hands, each doing what they do best".**

We don't ask one giant model to do everything. Instead, a 2.72 MB lightweight kernel
strings together five nodes — **Router / Notetaker / Planner / Action / Executor** —
and lets each small model play to its strengths. Precisely because MASE keeps the
architecture this simple, it leaves **infinite room** for what comes next:
multi-agent collaboration, MCP integrations, plug-in ecosystems.

**The beauty of open source is that no single person has to be perfect.**
If you share the values of transparency, minimalism, and collaboration —
welcome to MASE. Let's lay this foundation together, each contributing what we do best.

— *zbl1998-sdjn, Spring 2026*
