# Adaptive Verification Depth

Pluggable policy that varies verifier depth based on retrieval confidence.
Default OFF — gated by `MASE_ADAPTIVE_VERIFY=1`. Zero behavioral change when
disabled (LME 84.8% baseline must hold).
(Baseline tracked in `docs/benchmark_claims/longmemeval.json`.)

## Motivation

Today every LongMemEval question runs through the `MASE_LME_VERIFY=1` chain
(kimi-k2.5 cloud verifier), even when dense retrieval already returned a
near-exact, dominant match. That spends API quota and latency on cases where
the answer is essentially decided pre-verify. Conversely, the *hardest*
slices — multi-session synthesis and temporal reasoning — would benefit from
a second opinion, but currently get the same single verifier as the easy
ones.

Adaptive depth shifts compute from easy → hard:

- **Skip** the verifier when retrieval is high-confidence and dominant.
- **Single** verifier (status quo) for the medium band.
- **Dual** verifier vote for low-confidence or hard-qtype questions.

## Three-tier policy

| Tier   | Trigger                                                           | Verifier depth        | Expected effect                |
| ------ | ----------------------------------------------------------------- | --------------------- | ------------------------------ |
| skip   | `score ≥ 0.85` **AND** `top1 − top2 > 0.2`                        | none (use top-1)      | latency ↓, API spend ↓         |
| single | `0.5 ≤ score < 0.85` (or skip-tier without dominance gap)         | kimi-k2.5 (current)   | unchanged                      |
| dual   | `score < 0.5` **OR** `qtype ∈ {multi-session, temporal-reasoning}` | kimi-k2.5 + 2nd model | precision ↑ on hard slices     |

### Env overrides

| Variable                          | Default | Purpose                              |
| --------------------------------- | ------- | ------------------------------------ |
| `MASE_ADAPTIVE_VERIFY`            | `0`     | master gate (must be `1` to engage)  |
| `MASE_VERIFY_SKIP_THRESHOLD`      | `0.85`  | min top-1 score to consider skipping |
| `MASE_VERIFY_DUAL_THRESHOLD`      | `0.5`   | top-1 score below which dual fires   |
| `MASE_VERIFY_DOMINANCE_GAP`       | `0.2`   | min `top1 − top2` for skip tier      |

## Integration shape

`src/mase/adaptive_verify.py` is pure decision logic — no I/O, no model
calls. It exposes `AdaptiveVerifyPolicy().decide(score, candidates, qtype)`
returning `Literal["skip","single","dual"]`.

`src/mase/router.py` adds a tiny `adaptive_verify_decision(...)` hook that
returns `"single"` whenever the env flag is unset. Call sites that want to
opt in wrap their existing verifier dispatch with:

```python
depth = adaptive_verify_decision(score, candidates, qtype)
if depth == "skip":
    answer = top1_candidate
elif depth == "dual":
    answer = dual_verifier_vote(candidates)
else:
    answer = single_verifier(candidates)  # current path
```

Until any call site adds that wrapper, the module is fully inert.

## Expected impact (priors)

Based on LME retrieval-score histograms collected by
`benchmark_notetaker.py`:

- ~40% of questions hit the skip tier (high score, dominant top-1)
  → ~40% reduction in cloud verifier calls, proportional spend + latency
  savings on the easy band.
- ~15% land in the dual tier (low score or hard qtype). Cost there ~2×
  current per question, but concentrated on the slices that fail today.
- Net verifier-call delta: ≈ −25% (saves dominate the dual upcharge).
- Net accuracy delta: target +0.5–1.5 pts on multi-session +
  temporal-reasoning slices, neutral elsewhere.

## Ablation plan

Run on the LongMemEval 500-question set (or msr_slice20 for fast smoke):

| Run | `MASE_ADAPTIVE_VERIFY` | Skip thresh | Dual thresh | Notes                           |
| --- | ---------------------- | ----------- | ----------- | ------------------------------- |
| A   | `0`                    | —           | —           | baseline (must reproduce 84.8%) |
| B   | `1`                    | `0.85`      | `0.5`       | defaults                        |
| C   | `1`                    | `0.90`      | `0.5`       | conservative skip               |
| D   | `1`                    | `0.85`      | `0.6`       | aggressive dual                 |
| E   | `1`                    | `0.80`      | `0.4`       | aggressive skip + lenient dual  |

Metrics per run:
- overall LME accuracy (must not regress vs A by > 0.3 pts on B)
- accuracy by qtype (multi-session, temporal-reasoning, single-session-*)
- verifier call count (sum, mean per question)
- p50 / p95 end-to-end latency
- estimated API spend ($)

Decision rule:
- Promote default ON if some run beats A on overall accuracy **and** cuts
  verifier calls ≥ 25%.
- Else keep gated; pick the variant with the best (accuracy, cost) Pareto
  point and document it as `MASE_ADAPTIVE_VERIFY=1` recommended config.

## Failure modes & guards

- **Score scale drift.** If a future retriever returns scores on a
  different scale, defaults silently mis-tier. Mitigation: thresholds are
  env-overridable; ablation table E forces a re-tune.
- **Sparse candidates.** With < 2 candidates, dominance gap is treated as
  `+inf` (trivially dominant); skip tier still requires the score floor.
- **Unknown qtype.** Unknown qtypes never escalate to dual on their own —
  only the score band decides. Conservative by design.
- **Default-OFF inertness.** `adaptive_verify_decision` short-circuits to
  `"single"` when the gate env var is missing/`"0"`. Covered by
  `tests/test_adaptive_verify.py::test_default_off_router_hook_is_inert`.
