# NoLiMa 3-Way: MASE chunked vs paper baselines vs the memory-layer crowd

> **TL;DR** — On the NoLiMa needle-set ("ONLYDirect" / base score), our local
> `qwen2.5:7b` running under MASE's chunked executor goes from **1.79 % → 60.71 %**
> at 32k context vs single-pass on the same model. That number is the only
> point of this document. Everything else is honesty about what it does and
> doesn't mean.

## Why NoLiMa matters

NoLiMa (Modarressi et al., 2025, *arXiv:2502.05167*) is a needle-in-a-haystack
benchmark that **deliberately strips lexical overlap** between the question
and the supporting fact. Classic NIAH benchmarks reward models that grep —
the needle and the question share rare tokens, so attention has an easy job.
NoLiMa forces *latent associative reasoning*: the needle says "Yuki lives
next to the Semperoper", the question asks "which character has been to
Dresden". No shared keyword, no free ride. This is why frontier models that
score 99 % on Ruler can collapse to 25–70 % on NoLiMa at the *same* context
length. It's the cleanest public probe for whether a long-context system is
doing retrieval or reasoning.

## MASE chunked vs published baselines

| Context | GPT-4o¹ | Llama 3.3 70B¹ | Llama 3.1 70B¹ | qwen2.5:7b single-pass (ours) | **qwen2.5:7b + MASE chunked (ours)** |
|--------:|--------:|---------------:|---------------:|------------------------------:|-------------------------------------:|
|     4 k |   95.7 % |          87.4 % |          88.1 % |                       100.00 % |                          **100.00 %** |
|     8 k |   89.2 % |          81.5 % |          71.6 % |                        51.79 % |                          **100.00 %** |
|    16 k |   81.6 % |          72.1 % |          51.9 % |                        48.21 % |                           **75.00 %** |
|    32 k |   69.7 % |          59.5 % |          25.5 % |                         1.79 % |                           **60.71 %** |

¹ NoLiMa paper, Table 1 "base score" (needle set, ONLYDirect-equivalent).
Different model class, different vendor, different decoding stack — included
for **shape**, not for a leaderboard claim. Ours is reproduced locally on a
single workstation; theirs is from the paper.

![NoLiMa 3-way plot](assets/nolima_3way_lineplot.png)

The interesting line is the red diamond. A 7B model under a single chunked
executor matches or beats a 70B Llama 3.1 at every length ≥ 8k on this
benchmark, while the same 7B run as a single forward pass falls off a cliff
at 32k. The gap is the architecture, not the weights.

## Why mem0 / Letta / LangMem / Zep don't appear in this chart

Honest answer: **they don't run NoLiMa, and they shouldn't.** Those projects
are *chat-history memory layers* — they store user utterances across
sessions, summarise, retrieve, and feed back the relevant snippets. Their
public numbers are on **LongMemEval** (mem0), **LoCoMo** (mem0, Zep), and
their own conversational benchmarks. NoLiMa is a *raw long-context*
benchmark: the haystack is one document, fed to the model in one prompt.
Running mem0 on NoLiMa would mean asking a memory layer to do a job it was
never designed for, and the resulting number would be unfair to them and
uninformative to the reader.

So this isn't "MASE beats mem0 on NoLiMa". The headline is the inverse:
**MASE is the only single chunked-executor architecture publishing NoLiMa
numbers at this scale on a 7B local model.** That's a different lane, and
it's a lane no one else is currently driving in.

## Caveats we are not hiding

- **Model class mismatch.** Paper baselines are frontier 70B+ / GPT-4o.
  Ours is `qwen2.5:7b` via Ollama. Comparing absolute % is not the point;
  comparing the *slope* and the *delta vs our own single-pass* is.
- **ONLYDirect subset.** The harder NoLiMa-Hard split with multi-hop
  reasoning is still 0 % for us at every length — we don't claim otherwise
  (see `results/external/phase_a_summary.jsonl`, `nolima_hard*` rows).
- **Single seed, 56 items per length.** Same as the paper's needle set
  size; no cherry-picking across seeds.

## Reproduce

```bash
# raw runs (writes per-length JSONL into results/external/nolima_*):
python scripts/run_external_phase_a.py            # single-pass baseline
python scripts/run_external_phase_a_chunked.py    # MASE chunked

# rebuild the chart from the summary file:
python scripts/plot_nolima_3way.py
# → docs/assets/nolima_3way_lineplot.png
```

Source numbers: `results/external/phase_a_summary.jsonl`.
