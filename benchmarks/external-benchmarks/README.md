# External Benchmarks (Fetch Separately)

This directory holds third-party benchmark codebases & datasets that MASE
evaluates against. **They are intentionally NOT vendored into this repo**
(would add ~210 MB / 14k+ files of code we don't own and complicate license
hygiene).

To reproduce the numbers in the main README, populate this directory yourself.

## Required layout

```
benchmarks/external-benchmarks/
├── README.md                  ← this file (tracked)
├── BAMBOO/                    ← clone from upstream
│   ├── datasets/*.jsonl
│   ├── run_mase_official.py   (copy from scripts/external_adapters/bamboo)
│   └── evaluate_official_compat.py
└── NoLiMa/                    ← clone from upstream
    ├── data/
    │   ├── needlesets/*.json
    │   └── haystack/rand_shuffle/*.txt
    ├── evaluation/
    ├── run_mase_official.py   (copy from scripts/external_adapters/nolima)
    └── run_mase_chunked.py
```

## Fetch commands

### BAMBOO
Upstream: <https://github.com/RUCAIBox/BAMBOO> — Apache-2.0.

```bash
cd benchmarks/external-benchmarks
git clone --depth=1 https://github.com/RUCAIBox/BAMBOO.git BAMBOO
# Then copy our MASE adapters in:
cp ../../scripts/external_adapters/bamboo/*.py BAMBOO/
```

### NoLiMa
Upstream: <https://github.com/adobe-research/NoLiMa> — Adobe Research License
(non-commercial; check terms before redistribution).

```bash
cd benchmarks/external-benchmarks
git clone --depth=1 https://github.com/adobe-research/NoLiMa.git NoLiMa
cp ../../scripts/external_adapters/nolima/*.py NoLiMa/
```

> **License note**: We don't redistribute the upstream code or data here
> precisely to keep the MASE repo's Apache-2.0 license clean. If you need
> a turnkey environment, see Docker image (planned).

## Why not git submodules?

We considered it. Submodules pin a specific upstream commit, which is good
for reproducibility but bad for first-clone UX (extra `--recursive` step,
auth prompts on private mirrors). A `fetch.sh` is simpler. PRs welcome to
add submodule support behind a flag.

## Verify

After cloning, the regression suite in
`scripts/benchmarks/generalization_regression_suite.json` should resolve all
its referenced paths. Smoke check:

```bash
python scripts/benchmarks/run_generalization_regression.py --suite bamboo-official-smoke --dry-run
```
