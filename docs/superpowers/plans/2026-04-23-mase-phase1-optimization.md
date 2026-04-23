# MASE Phase 1 Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten MASE into a credible publishable baseline over the next 2–4 weeks without reducing current public capabilities.

**Architecture:** Implement the phase in five tracks: benchmark claim governance, config/profile governance, curated regression assets, architecture-boundary documentation, and low-risk legacy-path hollowing. The work deliberately avoids broad runtime rewrites and focuses on auditable metadata, guardrail tests, and minimal-path import cleanup.

**Tech Stack:** Python 3.10+, pytest, Ruff, Markdown docs, JSON manifests, existing benchmark runner/scripts, existing compatibility shim structure

---

## File Structure

- **Create:** `docs/benchmark_claims/README.md` — schema and usage for tracked benchmark claim manifests
- **Create:** `docs/benchmark_claims/longmemeval.json` — tracked LongMemEval claim manifest
- **Create:** `docs/benchmark_claims/lveval.json` — tracked LV-Eval claim manifest
- **Create:** `docs/benchmark_claims/nolima.json` — tracked NoLiMa claim manifest
- **Create:** `tests/test_benchmark_claim_manifest.py` — schema + doc-claim consistency guardrail
- **Create:** `config.profiles.json` — registry for `baseline` / `published` / `experimental` config lineage
- **Create:** `docs/CONFIG_PROFILES.md` — human-facing explanation of config intent and publication rules
- **Create:** `tests/test_config_profile_registry.py` — config profile registry validation
- **Create:** `tests/data/failure_clusters/manifest.json` — curated pack metadata
- **Create:** `tests/data/failure_clusters/longmemeval.json` — LongMemEval cluster cases
- **Create:** `tests/data/failure_clusters/lveval.json` — LV-Eval cluster cases
- **Create:** `tests/data/failure_clusters/nolima.json` — NoLiMa cluster cases
- **Create:** `tests/test_failure_cluster_pack.py` — golden cluster pack contract test
- **Create:** `docs/ARCHITECTURE_BOUNDARIES.md` — stable / compatibility / experimental boundary spec
- **Create:** `tests/test_project_surface_docs.py` — doc-guardrail tests for project surface language
- **Modify:** `README.md` — link benchmark claims + boundary docs and keep public wording aligned
- **Modify:** `docs/README_en.md` — same alignment in English
- **Modify:** `BENCHMARKS.md` — reference tracked manifests and per-lane wording
- **Modify:** `docs/LAUNCH_COPY.md` — published benchmark claims point at tracked manifests
- **Modify:** `docs/PUBLISH_CHECKLIST.md` — release checklist references tracked claim sources
- **Modify:** `docs/HYBRID_RECALL.md` — baseline references use tracked claim lane wording
- **Modify:** `docs/ADAPTIVE_VERIFY.md` — baseline references use tracked claim lane wording
- **Modify:** `v2测试.md` — local focused-input lane remains explicitly non-comparable
- **Modify:** `benchmarks/runner.py` — attach config profile metadata to benchmark summaries and reduce root-shim imports
- **Modify:** `mase_tools/memory/gc_agent.py` — low-risk switch from root shim import to `mase.model_interface`
- **Modify:** `scripts/benchmarks/run_api_hotswap_generalization_smoke.py` — low-risk switch to `mase.model_interface`
- **Modify:** `scripts/benchmarks/run_api_hotswap_longmem_smoke.py` — low-risk switch to `mase.model_interface`
- **Modify:** `scripts/benchmarks/run_api_hotswap_longmemeval_batch.py` — low-risk switch to `mase.model_interface`
- **Modify:** `tests/test_benchmark_harness.py` — keep harness path fix and add config profile assertions if needed
- **Modify:** `tests/test_longmemeval_failure_clusters.py` — load curated cluster manifest instead of ad hoc hardcoded expectations where helpful
- **Modify:** `LEGACY_SHIMS.md` — link to architecture-boundary document

---

### Task 1: Benchmark claim manifests and public-claim guardrails

**Files:**
- Create: `docs/benchmark_claims/README.md`
- Create: `docs/benchmark_claims/longmemeval.json`
- Create: `docs/benchmark_claims/lveval.json`
- Create: `docs/benchmark_claims/nolima.json`
- Create: `tests/test_benchmark_claim_manifest.py`
- Modify: `README.md`
- Modify: `docs/README_en.md`
- Modify: `BENCHMARKS.md`
- Modify: `docs/LAUNCH_COPY.md`
- Modify: `docs/PUBLISH_CHECKLIST.md`
- Modify: `docs/HYBRID_RECALL.md`
- Modify: `docs/ADAPTIVE_VERIFY.md`
- Modify: `v2测试.md`

- [ ] **Step 1: Write the failing manifest contract test**

Create `tests/test_benchmark_claim_manifest.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_DIR = ROOT / "docs" / "benchmark_claims"


def _load(name: str) -> dict:
    return json.loads((CLAIMS_DIR / name).read_text(encoding="utf-8"))


def _read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_claim_manifests_exist_and_have_core_fields() -> None:
    for filename in ("longmemeval.json", "lveval.json", "nolima.json"):
        payload = _load(filename)
        assert "benchmark" in payload
        assert "claims" in payload
        assert isinstance(payload["claims"], dict)
        assert payload["claims"], f"{filename} must define at least one claim lane"


def test_public_docs_reference_tracked_claim_language() -> None:
    readme = _read_text("README.md")
    readme_en = _read_text("docs/README_en.md")
    benchmarks = _read_text("BENCHMARKS.md")
    publish = _read_text("docs/PUBLISH_CHECKLIST.md")

    assert "docs/benchmark_claims/" in benchmarks
    assert "official substring" in readme
    assert "official substring" in readme_en
    assert "tracked claim manifest" in publish


def test_longmemeval_claim_lane_is_spelled_out() -> None:
    readme = _read_text("README.md")
    benchmarks = _read_text("BENCHMARKS.md")

    assert "84.8% (424/500)" in readme
    assert "61.0% (305/500)" in readme
    assert "LLM-judge, full_500 combined lane" in benchmarks
    assert "official substring-comparable lane" in benchmarks
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
pytest tests/test_benchmark_claim_manifest.py -q
```

Expected: FAIL because the manifests and tracked-claim references do not exist yet.

- [ ] **Step 3: Create manifest schema docs**

Create `docs/benchmark_claims/README.md`:

```md
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
- evidence status (`tracked` or `local_generated_untracked`)

Published docs must not state a headline benchmark number unless it is represented here.
```

- [ ] **Step 4: Create the LongMemEval manifest**

Create `docs/benchmark_claims/longmemeval.json`:

```json
{
  "benchmark": "LongMemEval-S",
  "claims": {
    "headline_full_500_llm_judge": {
      "score_pct": 84.8,
      "pass_count": 424,
      "sample_count": 500,
      "metric": "llm_judge",
      "config_profile": "published-cloud-longmemeval",
      "evidence": [
        {
          "path": "scripts/_lme_iter4_combined_summary.json",
          "status": "local_generated_untracked"
        }
      ]
    },
    "official_comparable_full_500_substring": {
      "score_pct": 61.0,
      "pass_count": 305,
      "sample_count": 500,
      "metric": "substring",
      "config_profile": "published-cloud-longmemeval",
      "evidence": [
        {
          "path": "scripts/_lme_iter2_summary.json",
          "status": "local_generated_untracked"
        }
      ]
    }
  }
}
```

- [ ] **Step 5: Create LV-Eval and NoLiMa manifests**

Create `docs/benchmark_claims/lveval.json`:

```json
{
  "benchmark": "LV-Eval EN",
  "claims": {
    "published_local_256k": {
      "score_pct": 88.71,
      "pass_count": 110,
      "sample_count": 124,
      "metric": "substring",
      "config_profile": "published-local-default",
      "evidence": [
        {
          "path": "BENCHMARKS.md",
          "status": "tracked"
        }
      ]
    }
  }
}
```

Create `docs/benchmark_claims/nolima.json`:

```json
{
  "benchmark": "NoLiMa ONLYDirect 32k",
  "claims": {
    "published_local_32k": {
      "score_pct": 60.71,
      "pass_count": 34,
      "sample_count": 56,
      "metric": "accuracy",
      "config_profile": "published-local-default",
      "evidence": [
        {
          "path": "README.md",
          "status": "tracked"
        }
      ]
    }
  }
}
```

- [ ] **Step 6: Align public docs to the tracked manifests**

Update README / English README / BENCHMARKS / launch and publish docs so they explicitly reference tracked claim language, for example:

```md
> Published benchmark claims are tracked under `docs/benchmark_claims/`.
```

And keep the LongMemEval wording in this shape:

```md
84.8% (424/500) — LLM-judge, full_500 combined lane
61.0% (305/500) — official substring-comparable lane
```

- [ ] **Step 7: Run tests to verify GREEN**

Run:

```bash
pytest tests/test_benchmark_claim_manifest.py -q
```

Expected: PASS

- [ ] **Step 8: Commit**

Run:

```bash
git add docs/benchmark_claims/README.md docs/benchmark_claims/longmemeval.json docs/benchmark_claims/lveval.json docs/benchmark_claims/nolima.json tests/test_benchmark_claim_manifest.py README.md docs/README_en.md BENCHMARKS.md docs/LAUNCH_COPY.md docs/PUBLISH_CHECKLIST.md docs/HYBRID_RECALL.md docs/ADAPTIVE_VERIFY.md v2测试.md
git commit -m "docs: add tracked benchmark claim manifests"
```

---

### Task 2: Configuration profile registry and result lineage

**Files:**
- Create: `config.profiles.json`
- Create: `docs/CONFIG_PROFILES.md`
- Create: `tests/test_config_profile_registry.py`
- Modify: `benchmarks/runner.py`

- [ ] **Step 1: Write the failing profile-registry test**

Create `tests/test_config_profile_registry.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_config_profile_registry_declares_intent_and_paths() -> None:
    payload = json.loads((ROOT / "config.profiles.json").read_text(encoding="utf-8"))
    profiles = payload["profiles"]

    assert profiles["published-local-default"]["path"] == "config.json"
    assert profiles["published-cloud-longmemeval"]["path"] == "config.lme_glm5.json"
    assert profiles["experimental-dual-gpu"]["path"] == "config.dual_gpu.json"
    assert profiles["published-nolima"]["path"] == "config.nolima.json"

    intents = {item["intent"] for item in profiles.values()}
    assert intents == {"baseline", "published", "experimental"}
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
pytest tests/test_config_profile_registry.py -q
```

Expected: FAIL because `config.profiles.json` does not exist yet.

- [ ] **Step 3: Create the config profile registry**

Create `config.profiles.json`:

```json
{
  "profiles": {
    "published-local-default": {
      "path": "config.json",
      "intent": "published",
      "benchmarks": ["lveval", "nolima"]
    },
    "published-cloud-longmemeval": {
      "path": "config.lme_glm5.json",
      "intent": "published",
      "benchmarks": ["longmemeval"]
    },
    "experimental-dual-gpu": {
      "path": "config.dual_gpu.json",
      "intent": "experimental",
      "benchmarks": ["lveval", "longmemeval"]
    },
    "baseline-cloud-example": {
      "path": "config.cloud.example.json",
      "intent": "baseline",
      "benchmarks": []
    },
    "published-nolima": {
      "path": "config.nolima.json",
      "intent": "published",
      "benchmarks": ["nolima"]
    }
  }
}
```

- [ ] **Step 4: Document config intent**

Create `docs/CONFIG_PROFILES.md`:

```md
# Config Profiles

- `baseline`: safe reference configuration, not itself a publish claim
- `published`: config lineage allowed to back public benchmark claims
- `experimental`: research-only or tuning-oriented config lineage
```

- [ ] **Step 5: Add runner support for config profile metadata**

Modify `benchmarks/runner.py` to load the profile registry and attach the resolved profile to result summaries:

```python
def _load_config_profiles() -> dict[str, Any]:
    registry_path = BASE_DIR / "config.profiles.json"
    if not registry_path.exists():
        return {}
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    return dict(payload.get("profiles") or {})


def _resolve_config_profile_name(config_path: Path, profiles: dict[str, Any]) -> str | None:
    normalized = config_path.name
    for name, data in profiles.items():
        if str(data.get("path")) == normalized:
            return name
    return None
```

And when building run metadata:

```python
profiles = _load_config_profiles()
resolved_profile = _resolve_config_profile_name(resolve_config_path(), profiles)
summary["config_profile"] = resolved_profile
```

- [ ] **Step 6: Run tests to verify GREEN**

Run:

```bash
pytest tests/test_config_profile_registry.py tests/test_benchmark_harness.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

Run:

```bash
git add config.profiles.json docs/CONFIG_PROFILES.md tests/test_config_profile_registry.py benchmarks/runner.py
git commit -m "feat: track benchmark config profiles"
```

---

### Task 3: Golden failure-cluster regression pack

**Files:**
- Create: `tests/data/failure_clusters/manifest.json`
- Create: `tests/data/failure_clusters/longmemeval.json`
- Create: `tests/data/failure_clusters/lveval.json`
- Create: `tests/data/failure_clusters/nolima.json`
- Create: `tests/test_failure_cluster_pack.py`
- Modify: `tests/test_longmemeval_failure_clusters.py`

- [ ] **Step 1: Write the failing pack-contract test**

Create `tests/test_failure_cluster_pack.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "tests" / "data" / "failure_clusters"


def _load(name: str) -> dict:
    return json.loads((PACK_DIR / name).read_text(encoding="utf-8"))


def test_failure_cluster_pack_has_required_benchmarks() -> None:
    manifest = _load("manifest.json")
    assert manifest["benchmarks"] == ["longmemeval", "lveval", "nolima"]

    for filename in ("longmemeval.json", "lveval.json", "nolima.json"):
        payload = _load(filename)
        assert payload["cases"], f"{filename} must declare at least one case"
        for case in payload["cases"]:
            assert "id" in case
            assert "failure_mode" in case
            assert "guardrail" in case
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
pytest tests/test_failure_cluster_pack.py -q
```

Expected: FAIL because the curated pack files do not exist yet.

- [ ] **Step 3: Create the pack manifest**

Create `tests/data/failure_clusters/manifest.json`:

```json
{
  "benchmarks": ["longmemeval", "lveval", "nolima"],
  "owner": "phase1-optimization",
  "purpose": "golden_failure_cluster_pack"
}
```

- [ ] **Step 4: Seed one file per benchmark**

Create `tests/data/failure_clusters/longmemeval.json`:

```json
{
  "cases": [
    {
      "id": "lme-multi-session-money-001",
      "failure_mode": "multi_session_aggregation",
      "guardrail": "counting_and_cross_session_total"
    }
  ]
}
```

Create `tests/data/failure_clusters/lveval.json`:

```json
{
  "cases": [
    {
      "id": "lveval-en-needle-001",
      "failure_mode": "needle_recall_miss",
      "guardrail": "planted_fact_recall"
    }
  ]
}
```

Create `tests/data/failure_clusters/nolima.json`:

```json
{
  "cases": [
    {
      "id": "nolima-direct-001",
      "failure_mode": "long_context_direct_answer_drop",
      "guardrail": "official_max_suite_tracking"
    }
  ]
}
```

- [ ] **Step 5: Hook LongMemEval cluster tests to curated data**

Modify `tests/test_longmemeval_failure_clusters.py` to load the curated IDs as a smoke guard:

```python
FAILURE_PACK = Path(__file__).resolve().parent / "data" / "failure_clusters" / "longmemeval.json"


def test_longmemeval_failure_pack_is_seeded() -> None:
    payload = json.loads(FAILURE_PACK.read_text(encoding="utf-8"))
    assert payload["cases"]
    assert payload["cases"][0]["failure_mode"] == "multi_session_aggregation"
```

- [ ] **Step 6: Run tests to verify GREEN**

Run:

```bash
pytest tests/test_failure_cluster_pack.py tests/test_longmemeval_failure_clusters.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

Run:

```bash
git add tests/data/failure_clusters/manifest.json tests/data/failure_clusters/longmemeval.json tests/data/failure_clusters/lveval.json tests/data/failure_clusters/nolima.json tests/test_failure_cluster_pack.py tests/test_longmemeval_failure_clusters.py
git commit -m "test: add golden failure cluster pack"
```

---

### Task 4: Stable / compatibility / experimental boundary docs

**Files:**
- Create: `docs/ARCHITECTURE_BOUNDARIES.md`
- Create: `tests/test_project_surface_docs.py`
- Modify: `README.md`
- Modify: `LEGACY_SHIMS.md`
- Modify: `docs/CONFIG_PROFILES.md`

- [ ] **Step 1: Write the failing doc-guardrail test**

Create `tests/test_project_surface_docs.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_architecture_boundary_doc_is_linked_and_named() -> None:
    boundary_doc = _read("docs/ARCHITECTURE_BOUNDARIES.md")
    readme = _read("README.md")
    legacy = _read("LEGACY_SHIMS.md")

    assert "Stable Core" in boundary_doc
    assert "Compatibility Surface" in boundary_doc
    assert "Experimental Surface" in boundary_doc
    assert "ARCHITECTURE_BOUNDARIES.md" in readme
    assert "ARCHITECTURE_BOUNDARIES.md" in legacy
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
pytest tests/test_project_surface_docs.py -q
```

Expected: FAIL because the boundary doc and links do not exist yet.

- [ ] **Step 3: Write the boundary document**

Create `docs/ARCHITECTURE_BOUNDARIES.md`:

```md
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
```

- [ ] **Step 4: Link boundary docs from public docs**

Update README and `LEGACY_SHIMS.md` with a line like:

```md
See `docs/ARCHITECTURE_BOUNDARIES.md` for the current stable / compatibility / experimental split.
```

And update `docs/CONFIG_PROFILES.md` to reference the same split:

```md
Published profiles support the stable core; experimental profiles belong to the experimental surface defined in `docs/ARCHITECTURE_BOUNDARIES.md`.
```

- [ ] **Step 5: Run tests to verify GREEN**

Run:

```bash
pytest tests/test_project_surface_docs.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

Run:

```bash
git add docs/ARCHITECTURE_BOUNDARIES.md tests/test_project_surface_docs.py README.md LEGACY_SHIMS.md docs/CONFIG_PROFILES.md
git commit -m "docs: define project architecture boundaries"
```

---

### Task 5: First batch of low-risk legacy-path hollowing

**Files:**
- Modify: `benchmarks/runner.py`
- Modify: `mase_tools/memory/gc_agent.py`
- Modify: `scripts/benchmarks/run_api_hotswap_generalization_smoke.py`
- Modify: `scripts/benchmarks/run_api_hotswap_longmem_smoke.py`
- Modify: `scripts/benchmarks/run_api_hotswap_longmemeval_batch.py`
- Modify: `tests/test_benchmark_harness.py`

- [ ] **Step 1: Write the failing import-surface test**

Append to `tests/test_benchmark_harness.py`:

```python
def test_runner_prefers_mase_module_imports() -> None:
    source = (Path(__file__).resolve().parents[1] / "benchmarks" / "runner.py").read_text(encoding="utf-8")
    assert "from mase.model_interface import" in source
    assert "from mase.topic_threads import" in source
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
pytest tests/test_benchmark_harness.py::test_runner_prefers_mase_module_imports -q
```

Expected: FAIL because `benchmarks/runner.py` still imports from root shims.

- [ ] **Step 3: Update low-risk imports**

Change imports in `benchmarks/runner.py`:

```python
from mase.model_interface import load_config, resolve_config_path
from mase.topic_threads import derive_thread_context, detect_text_language
```

Change import in `mase_tools/memory/gc_agent.py`:

```python
from mase.model_interface import ModelInterface
```

Change benchmark smoke scripts similarly:

```python
from mase.model_interface import load_config, resolve_config_path
```

- [ ] **Step 4: Run targeted tests to verify GREEN**

Run:

```bash
pytest tests/test_benchmark_harness.py tests/test_v2_refactor_modules.py -q
```

Expected: PASS

- [ ] **Step 5: Run full regression**

Run:

```bash
python -m pytest -q
python -m ruff check .
```

Expected: PASS

- [ ] **Step 6: Commit**

Run:

```bash
git add benchmarks/runner.py mase_tools/memory/gc_agent.py scripts/benchmarks/run_api_hotswap_generalization_smoke.py scripts/benchmarks/run_api_hotswap_longmem_smoke.py scripts/benchmarks/run_api_hotswap_longmemeval_batch.py tests/test_benchmark_harness.py
git commit -m "refactor: hollow low-risk legacy imports"
```

---

## Self-Review Checklist

### Spec coverage

- Benchmark claim governance → Task 1
- Stable benchmark hierarchy and publishable wording → Task 1
- Config lineage tightening → Task 2
- Golden failure-cluster regression pack → Task 3
- Stable / compatibility / experimental boundary clarity → Task 4
- First low-risk legacy-path hollowing → Task 5
- Capability preservation via test/lint gates → Tasks 1–5

### Placeholder scan

- No placeholder shortcuts remain.
- Every task includes exact file paths, runnable commands, and concrete code snippets.

### Type / naming consistency

- Claim manifests consistently use `score_pct`, `pass_count`, `sample_count`, `metric`, `config_profile`, `evidence`.
- Config registry consistently uses `profiles` and `intent`.
- Failure-cluster pack consistently uses `cases`, `failure_mode`, and `guardrail`.
