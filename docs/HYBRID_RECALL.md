# Hybrid Recall (BM25 + Dense + Temporal-Aware Rerank)

## Status

**Optional / pluggable.** Disabled by default. Zero impact on the current
publishable LongMemEval baseline (61.0% official substring / 80.2% LLM-judge)
unless you opt in via environment flag.
(Baseline tracked in `docs/benchmark_claims/longmemeval.json`.)

## Rationale

Plan A retry shows the lowest LongMemEval qtype is **temporal-reasoning at
72.2%**. Existing recall is dense-vector + simple rerank, which:

1. ignores lexical exact matches (proper nouns, codes, numerals);
2. has no notion of "yesterday" / "上次" — temporal cues are wasted;
3. cannot leverage candidate timestamps even when they are present.

`HybridReranker` adds two complementary signals on top of the existing dense
score, gated behind `MASE_HYBRID_RECALL=1` so production behavior is
unchanged when the flag is absent.

## Formula

For each candidate:

```
score = α · dense_norm + β · bm25_norm + γ · temporal_norm
```

| Symbol | Default | Source |
| ------ | ------- | ------ |
| α      | 0.5     | min-max normalized `candidate["score"]` (existing dense score) |
| β      | 0.3     | min-max normalized BM25 over `candidate["text"]` (or `content`) |
| γ      | 0.2     | temporal score in `[0, 1]` (see below) |

Override weights with `MASE_HYBRID_RECALL_WEIGHTS="α,β,γ"`, e.g.
`MASE_HYBRID_RECALL_WEIGHTS="0.4,0.3,0.3"`.

### BM25

Uses `rank_bm25.BM25Okapi` if installed; otherwise falls back to a tiny
inline implementation (`_InlineBM25`) so no new dependency is required.
Tokenization is whitespace + word characters plus per-character CJK
unigrams, so the same scorer works for English and Chinese.

### Temporal scoring

1. Detect a temporal cue in the query (`yesterday`, `last week`,
   `recently`, `我上次`, `之前`, `昨天`, `上周`, …) → pick a target window
   (2 / 7 / 31 / 30 days).
2. Coerce candidate `timestamp` (also tries `ts`, `created_at`).
3. If candidate falls inside the cued window → score = 1.0; else exponential
   decay outside the window.
4. With no cue, falls back to a gentle 30-day half-life recency score
   capped at 0.5 so it cannot dominate.

If the candidate has no parseable timestamp, the temporal component is
0 (neutral) — the reranker degrades gracefully to dense + BM25.

## How to enable

```bash
# Linux / macOS
export MASE_HYBRID_RECALL=1
# optional: tune weights
export MASE_HYBRID_RECALL_WEIGHTS="0.5,0.3,0.2"
```

```powershell
# Windows
$env:MASE_HYBRID_RECALL = "1"
$env:MASE_HYBRID_RECALL_WEIGHTS = "0.5,0.3,0.2"
```

The hook lives in `NotetakerAgent.execute_tool`: when
`mase2_search_memory` is invoked **and** the env flag is set, the returned
candidate list is reranked in-process. Errors in the reranker are swallowed
to guarantee no regression.

## Environment variables

| Variable | Default | Effect |
| -------- | ------- | ------ |
| `MASE_HYBRID_RECALL` | `0` | `1` enables the reranker hook |
| `MASE_HYBRID_RECALL_WEIGHTS` | `0.5,0.3,0.2` | comma-separated α,β,γ |

## Programmatic use

```python
from mase.hybrid_recall import HybridReranker

reranker = HybridReranker()  # or HybridReranker(alpha=0.5, beta=0.3, gamma=0.2)
ranked = reranker.rerank(
    query="what did we agree on yesterday?",
    candidates=[
        {"text": "...", "score": 0.81, "timestamp": "2025-01-09T10:00:00"},
        ...
    ],
)
```

The function is pure: input candidates are not mutated. Each output
candidate is a shallow copy with two extra keys: `hybrid_score` and
`hybrid_components` (`dense`, `bm25`, `temporal`, `weights`).

## Ablation plan

Goal: lift LongMemEval **temporal-reasoning** qtype from 72.2% → ~78%
without regressing the publishable overall baseline.

```bash
# Baseline (flag OFF — should reproduce 61.0% official / 80.2% judge)
python scripts/run_lme_iter4_retry_part2.py

# With hybrid recall
MASE_HYBRID_RECALL=1 python scripts/run_lme_iter4_retry_part2.py

# Weight sweep examples
MASE_HYBRID_RECALL=1 MASE_HYBRID_RECALL_WEIGHTS="0.4,0.3,0.3" \
    python scripts/run_lme_iter4_retry_part2.py
MASE_HYBRID_RECALL=1 MASE_HYBRID_RECALL_WEIGHTS="0.5,0.2,0.3" \
    python scripts/run_lme_iter4_retry_part2.py
```

Compare per-qtype accuracy; in particular monitor:

- `temporal-reasoning` (target: +5 pp)
- `single-session-preference` (must not regress)
- overall accuracy (must remain at or above the publishable baseline)

## Safety

- Module performs no I/O and no model calls.
- Default behavior is unchanged: when `MASE_HYBRID_RECALL` is unset, the
  reranker is never imported by the search path.
- Any exception inside the rerank hook is caught — original results are
  returned untouched.
- Optional `rank_bm25` dependency is **not** added to `requirements.txt`;
  inline BM25 is used as fallback.
