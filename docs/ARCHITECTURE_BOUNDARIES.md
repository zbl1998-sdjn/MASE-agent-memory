# Architecture Boundaries

## Stable Core

- `src/mase/`
- `benchmarks/runner.py`
- tracked benchmark claim manifests

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
