# LongMemEval Claim Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit the published LongMemEval numbers, prove what `84.8%`, `61.0%`, and `306 focused_input` each mean, and align all repo-facing claims without reducing existing capability.

**Architecture:** Build a single tracked source of truth for the LongMemEval headline claim, then update README/docs to match that evidence. Keep public API and benchmark entrypoints unchanged; only repair benchmark provenance, wording, labels, and consistency checks.

**Tech Stack:** Python 3.10+, pytest, ripgrep/git, Markdown docs, existing benchmark scripts and result summaries

---

## File Map

- **Create:** `docs/benchmark_claims/longmemeval.json` — tracked canonical claim manifest for LongMemEval headline + official-comparable metric
- **Create:** `tests/test_longmemeval_claim_consistency.py` — regression test that validates docs match the tracked claim manifest
- **Modify:** `README.md` — Chinese headline benchmark row and supporting wording
- **Modify:** `docs/README_en.md` — English headline benchmark row and supporting wording
- **Modify:** `BENCHMARKS.md` — LongMemEval section, metric-lane explanation, and best-run wording
- **Modify:** `docs/LAUNCH_COPY.md` — public launch copy that currently repeats `84.8%`
- **Modify:** `docs/PUBLISH_CHECKLIST.md` — review answers / launch checklist language
- **Modify:** `docs/HYBRID_RECALL.md` — baseline references tied to `84.8%`
- **Modify:** `docs/ADAPTIVE_VERIFY.md` — baseline references tied to `84.8%`
- **Modify:** `v2测试.md` — clarify that its `306 focused_input` result is a different line, not the same claim lane
- **Optional modify if needed by evidence:** `CHANGELOG.md` — only if claim wording/history needs a correction note

---

### Task 1: Capture the canonical evidence

**Files:**
- Create: `docs/benchmark_claims/longmemeval.json`
- Inspect: `scripts/_lme_iter2_summary.json`
- Inspect: `scripts/_lme_rescored_summary.json`
- Inspect: `results/benchmark-longmemeval_s-focused-20260419-003640-452864.json`
- Inspect: `BENCHMARKS.md`
- Inspect: `README.md`
- Inspect: `docs/README_en.md`

- [ ] **Step 1: Write the canonical claim manifest**

Create `docs/benchmark_claims/longmemeval.json` with the actual claim axes that the repo must preserve:

```json
{
  "headline_claim": {
    "benchmark": "LongMemEval-S",
    "sample_count": 500,
    "score": 84.8,
    "pass_count": 424,
    "metric": "llm_judge",
    "basis": "rescored_iter2_full_500",
    "source_file": "scripts/_lme_rescored_summary.json"
  },
  "official_comparable_claim": {
    "benchmark": "LongMemEval-S",
    "sample_count": 500,
    "score": 61.0,
    "pass_count": 305,
    "metric": "substring",
    "basis": "iter2_full_500",
    "source_file": "scripts/_lme_iter2_summary.json"
  },
  "non_comparable_runs": [
    {
      "label": "focused_input_306_local_batch",
      "sample_count": 306,
      "score": 45.75,
      "metric": "substring_plus_llm_judge_per_case",
      "source_file": "results/benchmark-longmemeval_s-focused-20260419-003640-452864.json",
      "note": "Different input shape and sample count; do not compare directly to the 500-case headline claim."
    }
  ]
}
```

- [ ] **Step 2: Verify the manifest values against local artifacts**

Run:

```powershell
Set-Location E:\MASE-demo
python - <<'PY'
import json
from pathlib import Path

iter2 = json.loads(Path("scripts/_lme_iter2_summary.json").read_text(encoding="utf-8"))
rescored = json.loads(Path("scripts/_lme_rescored_summary.json").read_text(encoding="utf-8"))
focused = json.loads(Path("results/benchmark-longmemeval_s-focused-20260419-003640-452864.json").read_text(encoding="utf-8"))

assert iter2["n"] == 500
assert iter2["pass"] == 305
assert iter2["pct"] == 61.0

assert rescored["n"] == 500
assert rescored["judge_pass"] == 424
assert rescored["judge_pct"] == 84.8

assert focused["planned_sample_count"] == 306
print("verified")
PY
```

Expected: `verified`

- [ ] **Step 3: Commit the evidence manifest**

Run:

```bash
git add docs/benchmark_claims/longmemeval.json
git commit -m "docs: add LongMemEval claim manifest"
```

---

### Task 2: Add a failing consistency test

**Files:**
- Create: `tests/test_longmemeval_claim_consistency.py`
- Read: `docs/benchmark_claims/longmemeval.json`
- Read: `README.md`
- Read: `docs/README_en.md`
- Read: `BENCHMARKS.md`
- Read: `v2测试.md`

- [ ] **Step 1: Write the failing test**

Create `tests/test_longmemeval_claim_consistency.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_longmemeval_claims_are_labeled_consistently() -> None:
    claim = json.loads(_read("docs/benchmark_claims/longmemeval.json"))

    headline = claim["headline_claim"]
    official = claim["official_comparable_claim"]

    readme = _read("README.md")
    readme_en = _read("docs/README_en.md")
    benchmarks = _read("BENCHMARKS.md")
    local_audit = _read("v2测试.md")

    headline_token = f'{headline["score"]}%'
    headline_pair = f'({headline["pass_count"]}/{headline["sample_count"]})'
    official_token = f'{official["score"]}'

    assert headline_token in readme
    assert headline_pair in readme
    assert "LLM-judge" in readme

    assert headline_token in readme_en
    assert headline_pair in readme_en
    assert "LLM-judge" in readme_en

    assert headline_token in benchmarks
    assert official_token in benchmarks
    assert "Two scoring lanes are reported" in benchmarks

    assert "306 全量" in local_audit
    assert "focused_input" in local_audit
    assert "口径是否完全一致还需要再复核" not in local_audit
```

- [ ] **Step 2: Run the test to verify it fails on the current wording**

Run:

```bash
pytest tests/test_longmemeval_claim_consistency.py -q
```

Expected: FAIL, because current docs do not all describe the same claim lane and `v2测试.md` still leaves comparability unresolved.

- [ ] **Step 3: Commit the failing test**

Run:

```bash
git add tests/test_longmemeval_claim_consistency.py
git commit -m "test: add LongMemEval claim consistency coverage"
```

---

### Task 3: Align the benchmark docs to the manifest

**Files:**
- Modify: `README.md`
- Modify: `docs/README_en.md`
- Modify: `BENCHMARKS.md`
- Modify: `docs/LAUNCH_COPY.md`
- Modify: `docs/PUBLISH_CHECKLIST.md`
- Modify: `docs/HYBRID_RECALL.md`
- Modify: `docs/ADAPTIVE_VERIFY.md`
- Modify: `v2测试.md`
- Read: `docs/benchmark_claims/longmemeval.json`

- [ ] **Step 1: Update the README benchmark row and note**

Patch both README files so the LongMemEval row says the claim basis explicitly:

```markdown
| LongMemEval-S 500 | GLM-5 + kimi-k2.5 second opinion + **LLM-judge rescore** | **84.8%** (424/500) | **61.0% official substring** | **+23.8pp over official substring / +14.4pp over GLM-5 baseline substring** |
```

And add a one-line clarification immediately below the evidence table:

```markdown
> LongMemEval is reported on two lanes: **84.8%** is the repo's best **LLM-judge rescored full-500** result; **61.0%** is the strongest official substring-comparable score for that same iter2 full-500 run.
```

- [ ] **Step 2: Update `BENCHMARKS.md` to include the 84.8% provenance**

Revise the LongMemEval table/notes so it contains all three relevant facts:

```markdown
| Configuration | n | Official substring % | **LLM-judge / rescored %** | Notes |
|---|---|---|---|---|
| GLM-5 baseline (no multipass, no verifier) | 500 | 70.4 | **72.4** | same full_500 set |
| iter2 (multipass + kimi-k2.5 verifier) | 500 | **61.0** | **80.2** | direct iter2 judge lane |
| iter2 + targeted retry / rescore aggregate | 500 | _n/a_ | **84.8** (424/500) | repo headline LLM-judge claim |
| focused_input local batch | 306 | 45.75 | _do not compare directly_ | different sample count and input shape |
```
```

Also replace wording like “80.2% number is the headline LongMemEval result” with wording that explicitly separates:

```markdown
The official substring-comparable result is **61.0%** on iter2 full_500. The repo headline **84.8%** number is a full_500 LLM-judge rescored claim derived from the tracked retry/rescore lane.
```

- [ ] **Step 3: Update secondary docs that currently repeat 84.8% without basis**

Adjust the repeated references in:

- `docs/LAUNCH_COPY.md`
- `docs/PUBLISH_CHECKLIST.md`
- `docs/HYBRID_RECALL.md`
- `docs/ADAPTIVE_VERIFY.md`

Use this style:

```markdown
84.8% LongMemEval-S (LLM-judge rescored, full_500)
```

and, where helpful, pair it with:

```markdown
61.0% official substring on iter2 full_500
```

- [ ] **Step 4: Resolve the ambiguity in `v2测试.md`**

Replace the unresolved sentence with an explicit non-comparability statement:

```markdown
结论：这条 `140 / 306 = 45.75%` 结果来自 `focused_input` 形态的 `306` 样本本地批跑，**不是** README / BENCHMARKS 中 `500` 样本 LongMemEval-S headline claim 的同口径结果，不能直接横向比较。
```

- [ ] **Step 5: Run the test to verify docs now pass**

Run:

```bash
pytest tests/test_longmemeval_claim_consistency.py -q
```

Expected: PASS

- [ ] **Step 6: Commit the doc alignment**

Run:

```bash
git add README.md docs/README_en.md BENCHMARKS.md docs/LAUNCH_COPY.md docs/PUBLISH_CHECKLIST.md docs/HYBRID_RECALL.md docs/ADAPTIVE_VERIFY.md v2测试.md
git commit -m "docs: align LongMemEval claim wording"
```

---

### Task 4: Verify no capability regression and local/remote alignment

**Files:**
- Read: `README.md`
- Read: `docs/README_en.md`
- Read: `BENCHMARKS.md`
- Read: `docs/benchmark_claims/longmemeval.json`
- Verify against: `origin/main`

- [ ] **Step 1: Run targeted existing tests**

Run:

```bash
pytest tests/test_benchmark_harness.py tests/test_longmemeval_failure_clusters.py -q
```

Expected: PASS

- [ ] **Step 2: Run the new consistency test plus full quick suite**

Run:

```bash
pytest tests/test_longmemeval_claim_consistency.py -q
python -m pytest -q
python -m ruff check .
```

Expected:

- targeted doc-consistency test passes
- existing test suite passes
- Ruff passes

- [ ] **Step 3: Compare local wording to remote baseline**

Run:

```bash
git fetch origin
git diff -- README.md docs/README_en.md BENCHMARKS.md docs/LAUNCH_COPY.md docs/PUBLISH_CHECKLIST.md docs/HYBRID_RECALL.md docs/ADAPTIVE_VERIFY.md v2测试.md
git diff origin/main -- README.md docs/README_en.md BENCHMARKS.md docs/LAUNCH_COPY.md docs/PUBLISH_CHECKLIST.md docs/HYBRID_RECALL.md docs/ADAPTIVE_VERIFY.md v2测试.md
```

Expected: diff shows only the intended claim-alignment edits.

- [ ] **Step 4: Commit the verification checkpoint**

Run:

```bash
git add docs/benchmark_claims/longmemeval.json tests/test_longmemeval_claim_consistency.py README.md docs/README_en.md BENCHMARKS.md docs/LAUNCH_COPY.md docs/PUBLISH_CHECKLIST.md docs/HYBRID_RECALL.md docs/ADAPTIVE_VERIFY.md v2测试.md
git commit -m "chore: verify LongMemEval claim alignment"
```

---

## Self-Review Checklist

- Spec coverage:
  - dataset cardinality audit → Task 1 + Task 3
  - metric-lane audit → Task 1 + Task 3
  - local vs remote alignment → Task 4
  - low-risk remediation only → Task 3 + Task 4
- No placeholders remain.
- Public API / capability preservation is explicit: no runtime codepath removal, only evidence capture + wording alignment + consistency test coverage.
