# Architecture Boundaries

## Stable Core

- `src/mase/contracts/`: pure data contracts and compatibility-safe schemas.
- `src/mase/core/`: lifecycle/state-machine primitives with no API/UI/storage implementation dependency.
- `src/mase/governance/`: fact admission, evidence, retrieval compilation, review, evaluation, and verification.
- `src/mase/storage/interfaces.py`: storage protocols only; implementation packages must stay behind this interface.
- Remaining `src/mase/` modules are stable runtime surface unless explicitly listed as compatibility or experimental.
- `benchmarks/runner.py`
- tracked benchmark claim manifests

## Enterprise Dependency Rule

`contracts <- core <- governance <- retrieval/runtime <- api/workers/integrations/cli`.

Boundary gates:

- `contracts` must not import governance, storage implementations, FastAPI, or UI/API layers.
- `core` must not import FastAPI, CLI, concrete databases, or model providers.
- `governance` may depend on contracts/core/storage interfaces, but must not import API/CLI/integration layers.
- Boundary layers may orchestrate governance, but must not update governed fact status directly.

Run `python scripts/audit_architecture_imports.py --strict` and
`python scripts/audit_public_api_docstrings.py --strict` after changing stable
contracts, core, governance, or storage interfaces.

## Compatibility Surface

- root-level shim modules preserved for backward compatibility
- `LEGACY_SHIMS.md`

## Experimental Surface

- experimental benchmark scripts
- unpublished config profiles
- local generated benchmark artifacts

## Local-Only Surface

The following paths are intentionally outside the publishable surface and
should stay ignored or live in a sibling run directory such as `E:/MASE-runs`:

- large datasets and benchmark outputs (`data/`, `memory_runs/`, `results/`)
- local worktrees and agent scratch state (`.worktrees/`, `.claude/`)
- unpublished proposal experiments (`proposals/`)

Run `python scripts/audit_repo_hygiene.py` for an advisory report. CI runs the
same check with `--strict` on a clean checkout.

Set `MASE_RUNS_DIR` to redirect default runtime outputs out of the repository
root. For example, `MASE_RUNS_DIR=E:/MASE-runs` makes benchmark summaries land
under `E:/MASE-runs/results`, per-case benchmark memory under
`E:/MASE-runs/memory_runs`, and default memory files under
`E:/MASE-runs/memory`.
