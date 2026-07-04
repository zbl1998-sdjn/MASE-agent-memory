# ADR: Make Evidence Pack the default enterprise injection path

## Status

Accepted

## Context

The legacy fact-sheet path is useful for compatibility and benchmarks, but it can
hide governance metadata from the answer generation step. Enterprise deployments
need context injection to be replayable, evidence-backed, and compatible with
answer verification.

## Decision

When `MASE_ENTERPRISE_MODE=1`, `MASESystem` treats Evidence Pack injection as
enabled unless `MASE_EVIDENCE_PACK_INJECTION=0` explicitly disables it. The
legacy fact-sheet path remains the default outside enterprise mode.

## Consequences

- Enterprise mode gets a safer default context format.
- Existing local and benchmark behavior remains unchanged.
- Evidence Pack compilation failures still fall back to the legacy fact sheet so
  the runtime does not lose availability during governance-side incidents.
