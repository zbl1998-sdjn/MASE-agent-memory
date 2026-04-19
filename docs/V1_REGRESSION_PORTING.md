# V1 → V2 Regression Test Porting Roadmap

> Companion document to [`tests/conftest.py`](../tests/conftest.py) `collect_ignore`.
>
> **Honest disclosure**: 12 V1 regression test files are currently quarantined
> from `pytest` collection. They contain ~134 individual test functions that
> *would fail to even import* against the V2 surface. They are kept in-tree
> as **executable specifications** of behaviours V2 must eventually recover,
> not as currently-running protection.
>
> This file exists so that anyone reading the green `39/39 passed` line
> knows the full picture, and so that contributors have a per-file porting
> guide instead of a wall of import errors.

## Why these tests broke

The `src/` re-layout in V2 was not a pure file-move. It also reshaped:

1. **`ExecutorAgent.execute()` signature** — V1 took `mode=` keyword arguments
   and returned a slot-contract dict; V2 returns a `RouterDecision` and routes
   through `langgraph_orchestrator`.
2. **`event_bus` snapshot schema** — V1 emitted `{step, planner_state, slots}`,
   V2 emits LangGraph state deltas.
3. **Per-slot reasoning hooks** — V1 had `slot.on_compute(...)` callbacks for
   deterministic-count / oracle-checklist enforcement; V2 deleted them in
   favour of verifier-side guards.
4. **Notetaker write contract** — V1 wrote a single tuple, V2 writes
   `(content, summary, topic_tokens, metadata)` and now also mirrors to a
   tri-vault directory layout when `MASE_MEMORY_LAYOUT=tri`.

None of those four changes were rolled back when the user-facing benchmarks
(LV-Eval, NoLiMa, LongMemEval) were re-tuned for V2. We chose to **keep the
behaviour the new surface exposes** rather than restore the V1 internals.

## Quarantine table

| File | Tests | Failure mode | V2 porting strategy |
|------|------:|-------------|--------------------|
| `test_generalization_hardening.py` | ~52 | `ExecutorAgent.execute(..., mode=...)` no longer accepts `mode=` | Rewrite against `RouterDecision` from `langgraph_orchestrator.route_node`. The semantic check (no scope leakage, no abstention loop) is still valid; only the call surface changed. |
| `test_failure_cluster_targeted_regressions.py` | ~41 | Slot-contract internals (`PlannerState.slots[i].confidence`) | Rewrite as black-box tests at the `mase.run(query)` boundary. Group by failure cluster ID, assert on final answer + verifier verdict. |
| `test_event_bus_mvp.py` | ~33 | `event_bus.snapshot()` schema | Either drop (LangGraph already emits replayable state) or write a V2 `event_bus_v2.py` adapter that re-derives the V1 fields from LangGraph state. Lower priority. |
| `test_multi_session_reasoning_regressions.py` | ~10 | Per-slot reasoning hook removed; deterministic-count guard now lives in `verifier.py` | Move the `count(X) == N` assertions into `tests/verifier/` and call `verifier.check()` directly. |
| `test_msr_slice20_checklist_regressions.py` | ~6 | Same as above | Same as above. |
| `test_msr_slice20_retrieval_regressions.py` | ~6 | Retrieval API renamed (`router.search` → `langgraph_orchestrator.search_node`) | Mechanical rename + assertion shape change. ~30 min. |
| `test_msr_slice20_duration_regressions.py` | ~5 | Duration parser moved into `temporal_parser.py` | Re-target the import; logic identical. |
| `test_msr_slice20_money_regressions.py` | ~5 | Currency parser moved | Re-target import. ~10 min. |
| `test_longmemeval_failure_clusters.py` | ~4 | LME runner shape (`run_lme_iter*.py`) changed | Replace with a thin smoke test that invokes `scripts/run_lme_iter4_full500.py --limit 5`. |
| `test_scope_leakage_regressions.py` | ~4 | V1 scope-leakage checker; V2 abstention guard moved into verifier | Port asserts to verifier output. |
| `test_abstention_guard.py` | ~4 | `ExecutorAgent._refusal_message` removed | Verifier now emits abstention reasoning; assert on that instead. |
| `test_benchmark_harness.py` | n/a | Needs `scripts/` data dumps not in tree | Either ship a 5-row fixture or keep skipped (smoke-tested manually). |
| `test_temporal_parser.py` | n/a | Needs gitignored `longmemeval_oracle.json` | Either provide a tiny mock oracle or keep skipped. |

**Total quarantined functions**: ~134 (estimated by per-file count).
**Currently-running V2 tests**: 39 (cover MCP sandbox, schema migrations, tri-vault, verifier shape, ablation runner contracts).

## Re-enabling a file

1. Pick a file with the smallest "Tests" count first (best ROI).
2. Remove its line from `collect_ignore` in `tests/conftest.py`.
3. Run `pytest tests/<file> -x` and fix imports/asserts file-local.
4. When it passes, add a row to the changelog and delete the
   corresponding row above.

## Why this isn't fixed yet

Honest answer: the V2 work prioritised *user-visible* benchmark numbers
(LV-Eval, NoLiMa, LongMemEval) and engineering hygiene (P0 SQLite leak,
P1 loud migration, P3 tri-vault wiring, MCP real impl). The 134
internal-API tests were judged less load-bearing than the four
production-visible benchmarks, given finite hours.

This file makes that trade-off auditable. PRs to port any quarantined
file are welcome and small in scope.
