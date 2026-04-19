# Community Distribution Copy

These are outward-facing drafts. Keep them technical. Do not add marketing adjectives that the repo cannot defend.

## 1. Hacker News

### Recommended titles

1. **Show HN: Context windows stopped being the ceiling in our white-box AI memory system**
2. **Show HN: Zero hallucinations on verified clean long-context slices with a 2025 small-model cluster**
3. **Show HN: We turned long-context hallucinations into auditable errors**

### Submission text

I built MASE because I was frustrated by how hard AI memory systems are to inspect once they disappear behind embeddings, chunking, and reranking layers.

So this project takes a more explicit route: memory is externalized into plain files, retrieval and planning are separated, and the answer path can preserve fact sheets, candidate decisions, and audit traces.

Current repo-visible results:

- verified clean slices:
  - `32k-clean`: `10 / 10`
  - `64k-clean`: `10 / 10`
  - `256k-anchor-upgrade (20)`: `20 / 20`
- at `64k-clean`, local **Qwen3.5-27B** baseline: `0 / 10`, all timeout under the benchmark budget
- English LV-Eval full sweep: 794 / 821 = 96.71% across 16k-256k
- Cloud LongMemEval 100: 40 / 100 overall, with 93% route-to-memory and 100% retrieval hit on memory-routed cases

The interesting part to me is not only the score. It is that when the system fails, I can inspect where it failed.

### First comment

Hi HN, author here.

This project came from a simple frustration: once "memory" becomes a stack of embeddings, retrieval heuristics, and model stitching, it gets hard to answer basic debugging questions like:

- did the system retrieve the right evidence?
- did compression lose the needed fact?
- did the model ignore the evidence it got?

MASE is my attempt to make that path more white-box.

Another part of the story is that this is a 2025-era small-model cluster, not a frontier giant. And it still got those verified clean-line results.

The repo is still uneven. The LV-Eval line is much stronger than the current LongMemEval line, and I am deliberately not hiding that. The current public proof is also much stronger on memory-heavy recall than on complex coding / heavy math / richer logic workloads. But that asymmetry is also why I find the project useful: it reveals where the bottleneck has moved.

Happy to answer questions about the architecture, the benchmark setup, or the tradeoffs of using plain files instead of vector-DB-centric memory.

## 2. Reddit: r/LocalLLaMA

### Title

**We hit zero observed hallucinations on verified clean long-context slices using a 2025 small-model cluster**

### Post body

I want to share a project called MASE.

The core idea is pretty contrarian compared with a lot of current memory tooling:

- memory is externalized into JSON and Markdown
- routing, note-taking, planning, retrieval, and execution are split into separate layers
- the system keeps white-box traces instead of treating memory as "whatever the vector DB retrieved"

What I like about this setup is that it feels much more inspectable. If a memory question fails, I can inspect the saved memory, the retrieval path, the fact sheet, and the final answer behavior instead of guessing where the issue came from.

The current repo-visible results are strongest on LV-Eval:

- verified clean slices:
  - `32k-clean`: `10 / 10`
  - `64k-clean`: `10 / 10`
  - `256k-anchor-upgrade (20)`: `20 / 20`
- English full sweep: 794 / 821 = 96.71% across 16k-256k

LongMemEval is more mixed right now:

- Cloud LongMemEval 100: 40 / 100 overall
- route-to-memory: 93%
- retrieval hit on memory-routed cases: 100%

So the system is definitely not "done." The architecture still depends on model capability, which is exactly why hot swap matters. Some aggregation-heavy cases still expose the limit of smaller executors. But that is also why the white-box design matters: it makes the remaining failure modes legible.

Another thing I like about this direction is cost of iteration: most recent gains came from architecture changes, not another fine-tuning cycle.

If you care about local-model stacks, memory that can be audited, or using system design instead of brute-force context stuffing, I would love feedback from this community.

## 3. Reddit: r/MachineLearning

### Title

**[D] Context windows stopped being the ceiling on verified clean slices in a white-box AI memory system**

### Post body

I want to share a systems project called MASE that explores a different default for AI memory.

Instead of treating memory as "embed everything and retrieve approximate chunks later," MASE externalizes memory into plain files and decomposes the pipeline into routing, note-taking, planning, retrieval, and execution.

Why I think this is interesting:

1. it makes failure analysis more concrete
2. it separates retrieval correctness from answer-generation behavior
3. it creates an auditable trail from question to answer

The current benchmark evidence in the repo is strongest on LV-Eval, where the system shows a strong anti-decay trend:

- verified clean slices:
  - `32k-clean`: `10 / 10`
  - `64k-clean`: `10 / 10`
  - `256k-anchor-upgrade (20)`: `20 / 20`
- English full sweep: 794 / 821 = 96.71% across 16k-256k

The LongMemEval story is still weaker at the moment:

- Cloud LongMemEval 100: 40 / 100 overall
- route-to-memory: 93%
- retrieval hit on memory-routed cases: 100%

To me, that gap is the interesting part. It suggests that once routing and retrieval are strong enough, the next frontier becomes evidence compression, aggregation, execution discipline, and model capability rather than retrieval alone.

Curious whether others here have explored similarly white-box alternatives to vector-DB-centric memory stacks.

## 4. X / Twitter thread

### Post 1

**Context windows stopped being the ceiling on our verified clean line.**

MASE hit:
- `32k-clean`: `10 / 10`
- `64k-clean`: `10 / 10`
- `256k-anchor-upgrade (20)`: `20 / 20`

### Post 2

The bet is simple:

AI memory should be **inspectable**.

If the system answers from memory, you should be able to inspect:

- what was stored
- what was retrieved
- how it was compressed
- why the final answer was produced

### Post 3

So MASE splits the job into layers:

- router
- note-taker
- planner
- orchestrator
- executor

It is not "more context."
It is **more structure**.

### Post 4

And this was not done with a frontier giant.

It was done with a **2025-era small-model cluster**:
- `qwen2.5:0.5b / 1.5b / 3b / 7b`
- `deepseek-r1:7b`

### Post 5

The right way to phrase that is:

**MASE shows a strong anti-decay trend on LV-Eval.**

Not "we solved long context forever."
Precision matters.

### Post 6

The model story is also fun:

small open models for routing / note-taking
stronger executors for grounded answering / reasoning

This is a system-design project, not a "just use a bigger model" project.

### Post 7

The current LongMemEval story is more mixed:

- Cloud LongMemEval 100: **40 / 100**
- route-to-memory: **93%**
- retrieval hit on memory-routed cases: **100%**

That gap is useful. It tells us the bottleneck is not only retrieval anymore.

### Post 8

MASE is not a claim that model ability no longer matters.

It is the opposite:
the architecture made the dependency visible.
That is why **hot swap** is a core feature.

### Post 9

That is exactly why white-box systems matter.

When something fails, the failure leaves evidence.

You can inspect memory files, fact sheets, candidate decisions, and final traces instead of guessing.

### Post 10

The next step is turning MASE into infrastructure:

- MCP server for external memory
- OpenAI-compatible `/v1/chat/completions`

That is how this becomes more than a benchmark repo.

### Post 11

If you care about local models, auditable memory, or system design over brute-force context stuffing, check out MASE.

And yes, the memory is literally sitting in plain files.

### Post 12

One more point:
most recent MASE gains came from **architecture iteration**, not another fine-tuning cycle.

That makes the improvement loop faster and cheaper.

## 5. Suggested mentions

For X, mention only where truthful and appropriate:

- `@Alibaba_Qwen` or the current official Qwen account
- official DeepSeek account

Use a restrained thanks line:

> Built on top of open model work from Qwen and DeepSeek. Their releases made this kind of systems experimentation much easier.

