# Benchmark Claim Manifests

Tracked claim manifests define the publishable benchmark lanes for MASE.

Each manifest must declare:

- benchmark
- claim lane name
- score
- sample count
- metric lane
- config lineage
- evidence path
- evidence status (`tracked` for publishable headline lanes; `local_generated_untracked` is allowed only for explicitly diagnostic lanes)
- dataset provenance (`dataset_provenance`)
- anti-overfit run protocol (`run_protocol` and `anti_overfit`)

Published docs must not state a headline benchmark number unless it is represented here
and the lane is not marked `publishable_headline: false`.
