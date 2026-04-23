# MASE First-Phase Optimization Design

## Goal

Use the next **2–4 weeks** to move MASE from a strong research-grade prototype to a **credible publishable baseline** without reducing current public capabilities.

This phase is **not** primarily about chasing a new headline score. It is about tightening:

- benchmark credibility,
- architecture boundaries,
- regression protection,
- configuration discipline.

## Why this phase matters

MASE already has a strong core idea: **white-box memory governance instead of black-box recall dependency**.

What most limits the project right now is not lack of ideas. It is that several important surfaces are still too loose for a publishable engineering baseline:

- benchmark claims can drift across docs and result lanes,
- stable implementation and experimental/legacy paths still overlap,
- regression protection is too dependent on ad hoc reruns,
- configuration and published-result boundaries are not yet strict enough.

## Optimization principles

1. **Capability preservation first**
   Existing public capabilities must not regress.

2. **Evidence before claims**
   Every headline benchmark number must point to an auditable evidence chain.

3. **Stable core over score chasing**
   Tighten what MASE already does well before adding more experimental surface.

4. **Separation of concerns**
   Stable, compatibility, and experimental paths should not share the same outward narrative.

5. **Small, defensible improvements**
   Prefer low-risk structural tightening over broad rewrites.

## Existing 5 priority recommendations

1. **Benchmark / claim governance as a first-class system**
   Use manifest-style claim tracking plus consistency checks instead of relying on scattered docs and generated outputs.

2. **Explicit benchmark hierarchy**
   Treat LV-Eval / NoLiMa as primary battlegrounds and LongMemEval as secondary supporting evidence unless the measurement lane is equally mature and stable.

3. **Preserve public API while hollowing internal legacy**
   Keep outward compatibility, but steadily move live implementation away from legacy internals.

4. **Productize the memory engine core, not the full orchestration surface first**
   The most defensible product asset is the white-box memory/governance layer.

5. **Prepare for server-grade runtime deliberately**
   Do not let service-grade needs remain implicit; make them a planned next-stage target.

## Additional 5 recommendations

6. **Define a stable-core vs experimental boundary explicitly**
   Make it obvious which modules, configs, and docs represent supported baseline behavior and which are research lanes.

7. **Build a retrieval ablation matrix**
   Measure contributions of query rewrite, fact sheet shaping, rerank, verifier, routing, and fallback instead of relying on aggregate score intuition.

8. **Curate a golden failure-cluster pack**
   Preserve high-value failures from LongMemEval, LV-Eval, and NoLiMa as stable regression assets.

9. **Tighten configuration genealogy**
   Distinguish baseline, published, and experimental configs with explicit intent and naming.

10. **Pre-wire observability for future service runtime**
   Standardize evidence-chain, trace, and metrics outputs now so later service-grade work builds on existing structure.

## Recommended roadmap shape

### Recommended approach: **credibility-first closure**

This phase should be a **closure phase**, not a growth phase.

The focus is:

- make benchmark claims defensible,
- reduce ambiguity in architecture/story,
- install regression guardrails,
- clarify what is stable vs experimental.

### Alternatives considered

#### 1. Score-first optimization

Prioritize retrieval, verifier, and routing improvements immediately to push benchmark numbers higher.

**Why not now:**
This would likely increase capability in some lanes, but it also risks deepening claim drift and experimental sprawl before the current baseline is cleanly defined.

#### 2. Product-first optimization

Prioritize API/runtime/service packaging and observability first.

**Why not now:**
This would help long-term productization, but it would be built on top of still-loose benchmark and architecture boundaries.

#### 3. Credibility-first closure (**recommended**)

Tighten the project into a publishable, auditable baseline first, then use that baseline as the platform for future scoring and service/runtime work.

## 2–4 week optimization plan

### Week 1 — benchmark evidence closure

Focus:

- build/extend benchmark claim manifest coverage,
- link headline numbers to dataset, metric lane, config, and evidence path,
- add doc/claim consistency checks for published benchmark statements.

Expected outcome:

- README / benchmark docs / launch copy / publish checklists stop drifting apart.

### Week 2 — config and publication boundary closure

Focus:

- separate configs into `baseline`, `published`, and `experimental`,
- align result labels and benchmark output naming with those config classes,
- tighten which results are publishable vs internal-only.

Expected outcome:

- every published claim can point to a uniquely identified config lineage.

### Week 3 — regression and architecture boundary closure

Focus:

- create a minimum viable golden failure-cluster regression pack,
- document stable-core, compatibility, and experimental surfaces,
- identify low-risk legacy/live-path extractions without breaking outward behavior.

Expected outcome:

- regression protection starts guarding the most important failure modes,
- the project narrative no longer blurs `src/mase`, compatibility shims, and experimental paths.

### Week 4 — optional validation / release closure

Focus:

- run a publish-grade regression pass,
- ensure docs, benchmark summaries, and public messaging are aligned,
- publish a short “credible capability surface” summary.

Expected outcome:

- external readers can understand what MASE definitively supports today.

## P0 / P1 / P2 priorities

### P0 — must complete this phase

1. Headline benchmark claim governance
2. Published vs experimental config separation
3. Minimum failure-cluster regression pack
4. Stable-core / compatibility / experimental boundary documentation

### P1 — should complete if time allows

1. First batch of low-risk legacy-path hollowing
2. Unified benchmark result naming / manifests
3. Automated consistency checks across docs and published benchmark surfaces

### P2 — explicitly deferred to the next phase

1. Server-grade runtime
2. More ambitious semantic retrieval upgrades
3. Aggressive benchmark score chasing
4. Broader SDK / product surface expansion

## Concrete acceptance criteria

Phase 1 is complete when all of the following are true:

1. **All public headline benchmark numbers have tracked claim manifests**
   Each claim points to dataset scope, metric lane, config lineage, and evidence path.

2. **Public benchmark docs no longer contradict each other**
   README, benchmark docs, and public-facing launch/publish docs use aligned wording.

3. **At least one stable golden failure-cluster regression pack exists**
   It covers the highest-value failure modes across the project’s key benchmarks.

4. **Configurations are classified by intent**
   Baseline, published, and experimental configs are clearly separated.

5. **Architecture boundaries are documented clearly**
   The project explains what belongs to stable core, compatibility, and experimental surfaces.

6. **Current public capability does not regress**
   Existing test and verification gates remain green.

## Risks

### Risk: benchmark closure slows visible score improvements

Mitigation:

- treat this as an intentional trade-off;
- Phase 1 is about trust and repeatability, not maximizing fresh headline numbers.

### Risk: legacy clean-up grows into a refactor campaign

Mitigation:

- keep this phase at the documentation + low-risk extraction level;
- do not attempt sweeping compatibility deletion in this phase.

### Risk: “stable” and “experimental” remain socially, not technically, separated

Mitigation:

- pair documentation changes with config/result naming rules and consistency tests.

## What not to do in this phase

- Do not optimize primarily for one new benchmark score.
- Do not remove public-facing APIs just to make internals cleaner.
- Do not do a broad runtime rewrite.
- Do not treat experimental outputs as publishable by default.

## Intended outcome

At the end of this phase, MASE should feel like:

- a **credible engineering baseline**,
- with a **clear benchmark story**,
- a **defensible architecture narrative**,
- and the beginnings of a **true release discipline**.

That is the right foundation for the next phase of capability growth and productization.
