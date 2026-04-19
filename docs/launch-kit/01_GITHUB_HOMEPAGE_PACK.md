# MASE GitHub Homepage Pack

This pack is for the first 10 seconds on GitHub. The goal is not to explain everything. The goal is to make a strong technical claim, prove it fast, and make the repo feel auditable and runnable.

## 1. Recommended hero

### Option A

**Context Windows Stopped Being the Ceiling: MASE Hit 100% on Verified 32k / 64k / 256k LV-Eval Slices.**

### Option B

**Zero Hallucinations on the Verified Clean Line: MASE Did It with a 2025-Era Small-Model Cluster.**

### Option C

**We Already Did It: MASE Turned Long-Context Hallucinations into Auditable Errors.**

## 2. Recommended subheadline

Use one of these directly under the title:

> On verified LV-Eval slices, MASE made context windows stop being the ceiling by externalizing memory into files, routing across hot-swappable models, and keeping the full retrieval-to-answer chain auditable.

> Built on a 2025-era small-model cluster that many people would already call old, MASE hit 100% on verified clean slices without resorting to frontier-scale brute force.

## 3. Proof block for the top of README

Put this above the fold, before the long explanation.

```md
## Why this repo makes people stop scrolling

- **Verified zero-hallucination slices**:
  - `32k-clean`: **10 / 10**
  - `64k-clean`: **10 / 10**
  - `256k-anchor-upgrade (20)`: **20 / 20**
- **Fast on those verified slices**:
  - `32k-clean`: **6.57 s / sample**
  - `64k-clean`: **6.60 s / sample**
  - `256k-anchor-upgrade (20)`: **7.88 s / sample**
- **Bigger baseline did not win under the benchmark budget**:
  - at `64k-clean`, **MASE = 10 / 10**
  - local **Qwen3.5-27B = 0 / 10**, all timeout under the benchmark budget
- **2025-era small-model cluster**:
  - `qwen2.5:0.5b / 1.5b / 3b / 7b`
  - `deepseek-r1:7b`
- **Hot-swappable and auditable**:
  - per-role / per-mode model selection
  - `reload()`-based config hot swap for subsequent requests
  - `case_memory_dir`, `fact_sheet`, candidate decisions, logs, and final traces
```

## 4. Recommended benchmark framing

Lead with the sharpest **truthful** version:

> On the verified clean LV-Eval line, context windows stopped being the ceiling.

> On those verified slices, MASE showed zero observed hallucination / zero error behavior.

Use this table near the top:

| Slice | MASE | Avg latency | Baseline | Aggressive but safe claim |
|---|---:|---:|---:|---|
| `32k-clean` | `10 / 10` | `6.57 s` | `Qwen3.5-27B: 0 / 10 timeout` | Zero observed hallucinations on this verified slice |
| `64k-clean` | `10 / 10` | `6.60 s` | `Qwen3.5-27B: 0 / 10 timeout` | Context windows stop being the ceiling here |
| `256k-anchor-upgrade (20)` | `20 / 20` | `7.88 s` | `baseline skipped` | Zero-error verified 256k slice |
| English full sweep `16k-256k` | `794 / 821` | `-` | `-` | Strong anti-decay trend |
| Cloud LongMemEval 100 | `40 / 100` | `-` | `-` | Honest current limitation |

Recommended note under the table:

> Boundary note: "zero hallucinations" is defensible only for the verified clean slices above, not for every task the system can do. The English sweep is still best framed as an **anti-decay trend**, not a formal reverse-decay proof.

## 5. Architecture contrast block

Add a simple side-by-side diagram and pair it with this copy:

| Default RAG / Vector DB story | MASE story |
|---|---|
| Memory disappears into an embedding index | Memory is written as plain files |
| Retrieval quality is harder to audit | Retrieval, fact compression, and answer steps are inspectable |
| Bigger context often becomes the default fix | Routing, planning, compression, and execution are separated |
| Failure analysis is vague | You can inspect traces, fact sheets, and candidate decisions |

Caption:

> MASE is not "more context." It is **more structure**.

## 6. 3-minute aha demo copy

The current repo does **not** yet expose the `docker-compose up -d` story you want, so use the existing truthful quickstart for now.

```powershell
pip install ollama

ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull deepseek-r1:7b

python .\mase.py
```

Then use this exact demo sequence in the README:

```text
User: Please remember that the server port is 9909.
MASE: Stored.

User: Based on what I told you, write a Python config dict.
MASE: {"server_port": 9909, ...}
```

Immediately after that, show the file-system proof:

```powershell
Get-ChildItem .\memory -Recurse
Get-ChildItem .\memory\logs -Recurse
```

Caption:

> This is the point of MASE: the memory is not mystical. It is sitting in your filesystem.

## 7. Recommended "Why this exists" section

Use this wording:

> Most long-context demos still assume the model should remember by brute force. MASE takes the opposite view: reliable memory should be externalized, compressed, routed, and audited by the system.

> The interesting question is not "How many tokens can the model hold?" The interesting question is "Can the system still find, justify, and reuse the right evidence when context gets large?"

> The original intuition is embarrassingly simple: writing matters because it turns disappearing information into stable records; notes matter because information that gets written down is harder to lose. MASE treats AI memory the same way.

## 8. Small-model narrative

Use this angle aggressively, because it is one of the strongest social hooks:

> MASE is built around a split stack of open models. Small models handle routing and note-taking. Stronger executors handle grounded answering and reasoning. The point is not model worship. The point is **system design beating brute-force context stuffing**.

Push this point harder:

> This was not achieved with a 2026 frontier giant. It was achieved with a 2025-era small-model cluster that many people would already call old. That is exactly why the result is interesting.

And make the dependency story explicit:

> MASE is **not** a claim that model capability no longer matters. The repo already shows the opposite: some aggregation-heavy LongMemEval cases still expose the limits of a 7B execution layer. That is why hot swap is a core architectural feature, not a cosmetic one.

And say this clearly:

> Many of MASE's recent gains came from architecture changes — retrieval, compression, candidate adjudication, white-box prompting, and hot swapping — not from launching a new fine-tuning cycle. In practice, that means faster and cheaper iteration than retraining another model.

Keep it factual. Current repo-visible model story includes:

- `qwen2.5:0.5b` for routing
- `qwen2.5:1.5b` and `qwen2.5:3b` for note-taking and summaries
- `qwen2.5:7b` for grounded execution
- `deepseek-r1:7b` for deeper reasoning and planning

## 9. Known limits to state explicitly

Be candid about these points:

1. **Current public proof is strongest on memory-heavy fact recall and LongMemEval-style memory retrieval**, not on every AI workload.
2. **The repo does not yet provide a systematic public benchmark pack for complex coding, heavy math, or richer logic workloads.**
3. **Model capability still matters.** The architecture can suppress hallucinations, route evidence, and improve stability, but it cannot magically erase the capability ceiling of a weak executor.
4. **MASE is strongest when framed as a memory-system breakthrough**, not as proof that every downstream task is solved.

## 10. Visual asset shot list

Add these assets near the top of the README:

1. **MASE vs Vector DB diagram**
2. **LV-Eval summary chart**
3. **Animated GIF**: ask -> retrieve -> fact sheet -> answer -> JSON/Markdown files on disk
4. **One screenshot of `memory/` and `memory/logs/`**

Suggested captions:

- "Memory you can grep"
- "White-box traces instead of hidden embeddings"
- "The answer path is inspectable, not implied"

## 11. Claim guardrails

Do say:

- "context windows stopped being the ceiling on the verified clean line"
- "zero observed hallucinations on verified clean LV-Eval slices"
- "2025-era small-model cluster"
- "hot-swappable white-box memory system"
- "architecture iteration instead of more training"

Do **not** say unless you ship more evidence first:

- "zero hallucinations on every task"
- "model ability no longer matters"
- "state of the art on LongMemEval"
- "complex coding / math fully benchmarked"
- "fully deterministic end-to-end answers"
- "one-command docker setup" if it is not yet in the repo

