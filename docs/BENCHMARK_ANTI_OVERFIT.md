# Benchmark Anti-Overfit Policy

This project uses benchmark-specific harnesses, but publishable claims must not
depend on benchmark-id shortcuts or hidden answer-lane routing.

## Publishable Lanes

Publishable benchmark runs must satisfy all of the following:

- Runtime routing must not branch on `question_id`, `qid`, filename prefixes,
  or benchmark-specific id suffixes.
- Scripts that previously experimented with question-id bucket routing must set
  `MASE_LME_ROUTE_BY_QID=0`.
- Result tables must point to tracked claim manifests under
  `docs/benchmark_claims/`.
- Post-hoc retry, combined, or cherry-picked rerun lanes must be labelled as
  diagnostic and kept out of public headline numbers.

## Allowed Metadata

The runtime may use metadata that a real deployment could know before seeing
the answer:

- task family, such as `long_context_qa` or `long_memory`
- generic task profile, such as `candidate_evidence`; legacy benchmark profile
  names may be accepted only as compatibility aliases
- context-length bucket, such as 64k / 128k / 256k
- language and prompt-surface markers
- general question type when the dataset provides it as a task label rather
  than as an id-derived shortcut

This metadata is acceptable because it describes the work to perform, not the
identity of a benchmark case.

## Disallowed Shortcuts

The following patterns are not allowed in publishable lanes:

- `qid.startswith(...)`, `qid.endswith(...)`, or equivalent id parsing for
  answer strategy selection
- allowlists of benchmark question ids for hydration, verifier routing, or
  answer rewriting
- result-file retry merges presented as first-pass system performance
- tuning on a failed public slice and reporting the same slice as a clean holdout

## Diagnostics

Diagnostic runs are useful for engineering, but they must be labelled honestly.
They can use extra probes, rerun failed subsets, or compare routing variants if
their outputs are not promoted as public headline claims.

Current public docs follow this distinction:

- LongMemEval iter2 full-500 LLM-judge lane is publishable.
- LongMemEval iter2 full-500 substring lane is official-comparable.
- LongMemEval iter4 combined/retry lane is diagnostic only.

## Evidence Provenance

Every tracked evidence summary for a publishable lane must declare:

- `dataset_provenance`: data source, config/split or selection, sample count,
  and stable hashes when the runner captured them.
- `run_protocol`: whether sample ids were allowed for routing, how ids were
  used, what runtime identifier was exposed, and the anti-overfit policy
  version.
- `anti_overfit`: whether qid-bucket routing was disabled and whether the lane
  uses failed-slice retry.

New benchmark runs produced by `benchmarks.runner` include a dataset fingerprint
(`sample_ids_sha256` and `sample_payload_sha256`) in their JSON summary. Older
tracked summaries that predate this field must be marked
`capture_status=summary_only_legacy` instead of pretending to have a fingerprint.
Raw sample ids are retained only in result reporting; runtime state and benchmark
memory metadata receive a SHA-256 sample hash instead.

## External Generalization

Benchmark improvements should be checked against at least one suite that was
not used to tune the change. The repo keeps this as a separate workflow:

- `scripts/benchmarks/run_generalization_regression.py --official-max-only`
  keeps LongMemEval coverage while preferring the larger BAMBOO and NoLiMa
  official-max suites over tiny smoke-only slices.
- Synthetic smoke samples are useful as syntax and integration checks, but they
  are not publishable evidence of external generalization.
- If a change was tuned on one public slice, report that slice as development
  evidence and use a different source/config/length bucket as the holdout.

## Regression Guards

The test suite includes guards for the most important failure mode:

- `tests/test_overfit_guards.py` rejects question-id bucket routing in the
  benchmark runner.
- Publishable LongMemEval scripts are checked for `MASE_LME_ROUTE_BY_QID=0`.
- Claim-manifest tests ensure public docs reference tracked evidence.
- Claim evidence tests require provenance and a machine-readable anti-overfit
  protocol.
- CI runs `scripts/audit_anti_overfit.py --strict`.
- External adapters use `MASE_TASK_PROFILE` instead of benchmark-name profiles;
  the audit rejects new adapter routing through `MASE_BENCHMARK_PROFILE`.

If a future benchmark needs task-specific routing, add a task label or problem
classifier that can exist outside the benchmark. Do not route on sample ids.
