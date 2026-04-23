# MASE Strong Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift MASE from a credible publishable baseline to a strong engineering baseline by hardening release discipline, product surface, regression tiers, operational diagnostics, and README-headline benchmark closure without regressing current public capability.

**Architecture:** Build on Phase 1 artifacts instead of replacing them. Reuse tracked benchmark claim manifests, config lineage, architecture-boundary docs, and existing benchmark runners, then add one governed release bundle, one primary supported surface, one release verification tier system, one diagnostic bundle contract, and one README-headline rerun closure path.

**Tech Stack:** Python 3.10+, pytest, Ruff, Markdown docs, JSON manifests, existing benchmark runners under `scripts/benchmarks/`, FastAPI OpenAI-compat server, current `src/mase` trace models

---

## File Structure

- **Create:** `scripts/release/build_release_bundle.py` — emits the governed public release bundle manifest from current repo truth
- **Create:** `docs/release/current/manifest.json` — generated release bundle for public claims, capability docs, and release evidence
- **Create:** `tests/test_release_bundle.py` — verifies the release bundle contract and public-doc links
- **Create:** `docs/release/FIX_VALIDATION_LEDGER.md` — durable record of important failures, fixes, and verification outcomes
- **Create:** `docs/CAPABILITY_STATEMENT.md` — explicit supported / experimental / out-of-scope surface statement
- **Create:** `tests/test_release_docs.py` — verifies ledger and capability statement wiring
- **Create:** `docs/SUPPORTED_SURFACE.md` — declares the primary supported entrypoint and supported integration surface
- **Create:** `docs/TROUBLESHOOTING.md` — common setup/runtime failure guide for the supported path
- **Create:** `tests/test_supported_surface_docs.py` — verifies supported-surface and troubleshooting docs stay aligned
- **Create:** `scripts/release/run_release_checks.py` — executes smoke / standard / publish release verification tiers
- **Create:** `docs/RELEASE_VERIFICATION.md` — human-facing explanation of the three verification tiers
- **Create:** `tests/test_release_verification.py` — verifies release-tier command mapping and docs
- **Create:** `src/mase/diagnostics.py` — error classification and diagnostic bundle helpers
- **Create:** `tests/test_diagnostics.py` — verifies diagnostic helpers and trace/header surfacing
- **Create:** `scripts/release/record_readme_rerun.py` — records fresh README-headline rerun evidence into a tracked JSON artifact
- **Create:** `docs/release/README_HEADLINE_RUNBOOK.md` — exact rerun commands for README headline benchmarks
- **Create:** `tests/test_readme_headline_rerun.py` — verifies rerun runbook and recording script contract
- **Modify:** `README.md` — point public claims and quickstart at the governed release bundle and supported surface
- **Modify:** `docs/README_en.md` — same public-surface alignment in English
- **Modify:** `BENCHMARKS.md` — point benchmark narration at the release bundle and rerun closure
- **Modify:** `docs/PUBLISH_CHECKLIST.md` — replace scattered checks with release-tier and release-bundle references
- **Modify:** `docs/LAUNCH_COPY.md` — require governed release bundle and capability statement before launch
- **Modify:** `docs/CONFIG_PROFILES.md` — explain quickstart / published / experimental / local-dev usage of config paths
- **Modify:** `examples/README.md` — declare `examples/10_persistent_chat_cli.py` as the primary supported quickstart
- **Modify:** `examples/README_10.md` — link to supported surface and troubleshooting docs
- **Modify:** `integrations/README.md` — declare `integrations/openai_compat/server.py` as the supported product-facing integration surface
- **Modify:** `integrations/openai_compat/README.md` — align startup, config, and troubleshooting guidance
- **Modify:** `src/mase/models.py` — expose `trace_id` on `OrchestrationTrace`
- **Modify:** `src/mase/engine.py` — populate `trace_id` in returned traces
- **Modify:** `benchmarks/runner.py` — attach `diagnostic_bundle` to benchmark summaries using current config lineage and error counts
- **Modify:** `integrations/openai_compat/server.py` — use `mase_run()` and surface `X-MASE-Trace-Id`

---

### Task 1: Governed release bundle for public claims

**Files:**
- Create: `scripts/release/build_release_bundle.py`
- Create: `docs/release/current/manifest.json`
- Create: `tests/test_release_bundle.py`
- Modify: `README.md`
- Modify: `BENCHMARKS.md`
- Modify: `docs/PUBLISH_CHECKLIST.md`
- Modify: `docs/LAUNCH_COPY.md`

- [ ] **Step 1: Write the failing release-bundle test**

Create `tests/test_release_bundle.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "docs" / "release" / "current" / "manifest.json"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_bundle_lists_headlines_and_governance_artifacts() -> None:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))

    assert payload["headline_benchmarks"] == ["lveval", "nolima", "longmemeval"]
    assert payload["claim_manifests"]["lveval"] == "docs/benchmark_claims/lveval.json"
    assert payload["claim_manifests"]["nolima"] == "docs/benchmark_claims/nolima.json"
    assert payload["claim_manifests"]["longmemeval"] == "docs/benchmark_claims/longmemeval.json"
    assert payload["fix_validation_ledger"] == "docs/release/FIX_VALIDATION_LEDGER.md"
    assert payload["capability_statement"] == "docs/CAPABILITY_STATEMENT.md"


def test_public_docs_point_to_release_bundle() -> None:
    readme = _read("README.md")
    benchmarks = _read("BENCHMARKS.md")
    publish = _read("docs/PUBLISH_CHECKLIST.md")
    launch = _read("docs/LAUNCH_COPY.md")

    assert "docs/release/current/manifest.json" in readme
    assert "docs/release/current/manifest.json" in benchmarks
    assert "docs/release/current/manifest.json" in publish
    assert "docs/release/current/manifest.json" in launch
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
python -m pytest tests/test_release_bundle.py -q
```

Expected: FAIL because the release bundle and public links do not exist yet.

- [ ] **Step 3: Write the bundle generator**

Create `scripts/release/build_release_bundle.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "docs" / "release" / "current" / "manifest.json"

BUNDLE = {
    "headline_benchmarks": ["lveval", "nolima", "longmemeval"],
    "claim_manifests": {
        "lveval": "docs/benchmark_claims/lveval.json",
        "nolima": "docs/benchmark_claims/nolima.json",
        "longmemeval": "docs/benchmark_claims/longmemeval.json",
    },
    "fix_validation_ledger": "docs/release/FIX_VALIDATION_LEDGER.md",
    "capability_statement": "docs/CAPABILITY_STATEMENT.md",
    "publish_checklist": "docs/PUBLISH_CHECKLIST.md",
    "launch_copy": "docs/LAUNCH_COPY.md",
}


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(BUNDLE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate the initial release bundle**

Run:

```bash
python scripts/release/build_release_bundle.py
```

Expected: `docs/release/current/manifest.json` is created.

- [ ] **Step 5: Wire public docs to the bundle**

Add a short release-bundle pointer to the public docs.

Update `README.md` with:

```md
> Public benchmark claims are governed by `docs/release/current/manifest.json`.
```

Update `BENCHMARKS.md` with:

```md
> Release-facing benchmark claims are bundled in `docs/release/current/manifest.json`.
```

Update `docs/PUBLISH_CHECKLIST.md` with:

```md
> Release bundle source of truth: `docs/release/current/manifest.json`
```

Update `docs/LAUNCH_COPY.md` with:

```md
> Do not launch from ad hoc notes. Launch claims must match `docs/release/current/manifest.json`.
```

- [ ] **Step 6: Run the test to verify GREEN**

Run:

```bash
python -m pytest tests/test_release_bundle.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

Run:

```bash
git add scripts/release/build_release_bundle.py docs/release/current/manifest.json tests/test_release_bundle.py README.md BENCHMARKS.md docs/PUBLISH_CHECKLIST.md docs/LAUNCH_COPY.md
git commit -m "feat: add governed release bundle"
```

---

### Task 2: Capability statement and fix-validation ledger

**Files:**
- Create: `docs/CAPABILITY_STATEMENT.md`
- Create: `docs/release/FIX_VALIDATION_LEDGER.md`
- Create: `tests/test_release_docs.py`
- Modify: `docs/release/current/manifest.json`
- Modify: `README.md`
- Modify: `docs/README_en.md`

- [ ] **Step 1: Write the failing release-docs test**

Create `tests/test_release_docs.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_capability_statement_and_validation_ledger_exist() -> None:
    bundle = json.loads((ROOT / "docs" / "release" / "current" / "manifest.json").read_text(encoding="utf-8"))
    capability = _read("docs/CAPABILITY_STATEMENT.md")
    ledger = _read("docs/release/FIX_VALIDATION_LEDGER.md")

    assert bundle["capability_statement"] == "docs/CAPABILITY_STATEMENT.md"
    assert bundle["fix_validation_ledger"] == "docs/release/FIX_VALIDATION_LEDGER.md"
    assert "Supported Today" in capability
    assert "Experimental" in capability
    assert "Out of Scope" in capability
    assert "| Issue | Fix | Verification |" in ledger


def test_readme_points_to_capability_statement() -> None:
    readme = _read("README.md")
    readme_en = _read("docs/README_en.md")

    assert "CAPABILITY_STATEMENT.md" in readme
    assert "CAPABILITY_STATEMENT.md" in readme_en
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
python -m pytest tests/test_release_docs.py -q
```

Expected: FAIL because the capability statement and validation ledger do not exist yet.

- [ ] **Step 3: Write the capability statement**

Create `docs/CAPABILITY_STATEMENT.md`:

```md
# MASE Capability Statement

## Supported Today

- White-box memory pipeline via `src/mase/`
- Governed benchmark claims via `docs/benchmark_claims/`
- Primary quickstart path via `examples/10_persistent_chat_cli.py`
- Supported product-facing integration via `integrations/openai_compat/server.py`

## Experimental

- unpublished benchmark scripts
- experimental config profiles
- local generated benchmark artifacts not yet promoted into the release bundle

## Out of Scope

- broad server-grade runtime guarantees
- high-concurrency production deployment guarantees
- unsupported benchmark claims without release-bundle evidence
```

- [ ] **Step 4: Seed the fix-validation ledger**

Create `docs/release/FIX_VALIDATION_LEDGER.md`:

```md
# Fix and Validation Ledger

| Issue | Fix | Verification |
|---|---|---|
| LongMemEval claim drift across docs | Added tracked claim manifests and doc-claim tests | `python -m pytest tests/test_benchmark_claim_manifest.py -q` |
| Config lineage ambiguity | Added `config.profiles.json` and benchmark summary `config_profile` wiring | `python -m pytest tests/test_config_profile_registry.py tests/test_benchmark_harness.py -q` |
| Failure knowledge trapped in ad hoc notes | Added curated failure-cluster pack and smoke guard | `python -m pytest tests/test_failure_cluster_pack.py tests/test_longmemeval_failure_clusters.py -q` |
```

- [ ] **Step 5: Link the new docs**

Update `README.md` with:

```md
Capability boundaries and honest support claims live in `docs/CAPABILITY_STATEMENT.md`.
```

Update `docs/README_en.md` with:

```md
Supported / experimental / out-of-scope claims live in `docs/CAPABILITY_STATEMENT.md`.
```

- [ ] **Step 6: Run the test to verify GREEN**

Run:

```bash
python -m pytest tests/test_release_docs.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

Run:

```bash
git add docs/CAPABILITY_STATEMENT.md docs/release/FIX_VALIDATION_LEDGER.md tests/test_release_docs.py README.md docs/README_en.md
git commit -m "docs: add capability statement and validation ledger"
```

---

### Task 3: Primary supported surface and troubleshooting

**Files:**
- Create: `docs/SUPPORTED_SURFACE.md`
- Create: `docs/TROUBLESHOOTING.md`
- Create: `tests/test_supported_surface_docs.py`
- Modify: `README.md`
- Modify: `docs/README_en.md`
- Modify: `examples/README.md`
- Modify: `examples/README_10.md`
- Modify: `integrations/README.md`
- Modify: `integrations/openai_compat/README.md`
- Modify: `docs/CONFIG_PROFILES.md`

- [ ] **Step 1: Write the failing supported-surface test**

Create `tests/test_supported_surface_docs.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_supported_surface_declares_primary_entrypoint_and_api_surface() -> None:
    surface = _read("docs/SUPPORTED_SURFACE.md")
    troubleshooting = _read("docs/TROUBLESHOOTING.md")
    readme = _read("README.md")
    examples = _read("examples/README.md")
    integrations = _read("integrations/README.md")

    assert "examples/10_persistent_chat_cli.py" in surface
    assert "integrations/openai_compat/server.py" in surface
    assert "SUPPORTED_SURFACE.md" in readme
    assert "TROUBLESHOOTING.md" in readme
    assert "examples/10_persistent_chat_cli.py" in examples
    assert "integrations/openai_compat/server.py" in integrations
    assert "Missing API key" in troubleshooting
    assert "MASE_CONFIG_PATH" in troubleshooting
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
python -m pytest tests/test_supported_surface_docs.py -q
```

Expected: FAIL because the supported-surface and troubleshooting docs do not exist yet.

- [ ] **Step 3: Write the supported-surface doc**

Create `docs/SUPPORTED_SURFACE.md`:

```md
# Supported Surface

## Primary Supported Entrypoint

- `examples/10_persistent_chat_cli.py`
- Use this path for first-run onboarding and quickstart validation

## Supported Product-Facing Integration Surface

- `integrations/openai_compat/server.py`
- Use this path when exposing MASE behind an OpenAI-compatible API

## Secondary Surfaces

- MCP server and framework integrations remain supported at MVP level, but they are not the primary onboarding path for this phase

## Not the Supported Path

- ad hoc benchmark scripts
- legacy root-level shims
- unpublished experimental configs
```

- [ ] **Step 4: Write the troubleshooting guide**

Create `docs/TROUBLESHOOTING.md`:

```md
# Troubleshooting

## Missing API key

Check `.env` or your shell environment for the provider named in your config.

## Wrong config file

Run with `MASE_CONFIG_PATH` set explicitly and confirm the path exists.

## Empty memory or missing history

Check the DB path and whether you started from `examples/10_persistent_chat_cli.py --reset`.

## Benchmark artifacts do not match README

Do not update README by hand. Rebuild release evidence and review `docs/release/current/manifest.json`.
```

- [ ] **Step 5: Align entrypoint and config docs**

Update the docs to point at the new supported surface.

Update `README.md` Quick Start to end with:

```md
Primary supported quickstart: `python examples/10_persistent_chat_cli.py`
```

Update `docs/README_en.md` with:

```md
Primary supported quickstart: `python examples/10_persistent_chat_cli.py`
```

Update `examples/README.md` with:

```md
`10_persistent_chat_cli.py` is the primary supported onboarding path for this phase.
```

Update `examples/README_10.md` with:

```md
For support boundaries and common failures, see `docs/SUPPORTED_SURFACE.md` and `docs/TROUBLESHOOTING.md`.
```

Update `integrations/README.md` with:

```md
For this phase, the OpenAI-compatible server is the primary supported product-facing integration surface.
```

Update `integrations/openai_compat/README.md` with:

```md
This is the supported API-facing surface for the current strong-baseline phase.
```

Update `docs/CONFIG_PROFILES.md` with:

```md
Use `config.json` for quickstart, tracked `published-*` profiles for governed claims, and `experimental-*` only for non-release work.
```

- [ ] **Step 6: Run the test to verify GREEN**

Run:

```bash
python -m pytest tests/test_supported_surface_docs.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

Run:

```bash
git add docs/SUPPORTED_SURFACE.md docs/TROUBLESHOOTING.md tests/test_supported_surface_docs.py README.md docs/README_en.md examples/README.md examples/README_10.md integrations/README.md integrations/openai_compat/README.md docs/CONFIG_PROFILES.md
git commit -m "docs: declare supported surface and troubleshooting path"
```

---

### Task 4: Release verification tiers

**Files:**
- Create: `scripts/release/run_release_checks.py`
- Create: `docs/RELEASE_VERIFICATION.md`
- Create: `tests/test_release_verification.py`
- Modify: `docs/PUBLISH_CHECKLIST.md`

- [ ] **Step 1: Write the failing release-tier test**

Create `tests/test_release_verification.py`:

```python
from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_check_tiers_are_declared() -> None:
    module = runpy.run_path(str(ROOT / "scripts" / "release" / "run_release_checks.py"))
    tiers = module["TIERS"]

    assert list(tiers) == ["smoke", "standard", "publish"]
    assert any("tests/test_benchmark_claim_manifest.py" in " ".join(cmd) for cmd in tiers["smoke"])
    assert any("tests/test_supported_surface_docs.py" in " ".join(cmd) for cmd in tiers["standard"])
    assert any("python -m pytest -q" == " ".join(cmd) for cmd in tiers["publish"])


def test_release_verification_doc_links_publish_tier() -> None:
    text = (ROOT / "docs" / "RELEASE_VERIFICATION.md").read_text(encoding="utf-8")
    assert "smoke" in text
    assert "standard" in text
    assert "publish" in text
    assert "python scripts/release/run_release_checks.py --tier publish" in text
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
python -m pytest tests/test_release_verification.py -q
```

Expected: FAIL because the release-check script and verification doc do not exist yet.

- [ ] **Step 3: Write the release-tier runner**

Create `scripts/release/run_release_checks.py`:

```python
from __future__ import annotations

import argparse
import subprocess


TIERS = {
    "smoke": [
        ["python", "-m", "pytest", "tests/test_benchmark_claim_manifest.py", "tests/test_release_bundle.py", "-q"],
    ],
    "standard": [
        ["python", "-m", "pytest", "tests/test_config_profile_registry.py", "tests/test_supported_surface_docs.py", "tests/test_failure_cluster_pack.py", "tests/test_project_surface_docs.py", "-q"],
        ["python", "-m", "ruff", "check", "."],
    ],
    "publish": [
        ["python", "-m", "pytest", "-q"],
        ["python", "-m", "ruff", "check", "."],
        ["python", "scripts/release/build_release_bundle.py"],
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=TIERS.keys(), required=True)
    args = parser.parse_args()
    for cmd in TIERS[args.tier]:
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Document the release tiers**

Create `docs/RELEASE_VERIFICATION.md`:

```md
# Release Verification

## smoke

- fast checks for claim governance and release-bundle integrity

## standard

- stronger project-surface and regression checks for day-to-day work

## publish

- full repo test suite
- Ruff
- release-bundle rebuild

Run:

`python scripts/release/run_release_checks.py --tier publish`
```

- [ ] **Step 5: Point the publish checklist at the new release gate**

Update `docs/PUBLISH_CHECKLIST.md` with:

```md
Before publishing, run `python scripts/release/run_release_checks.py --tier publish`.
```

- [ ] **Step 6: Run the test to verify GREEN**

Run:

```bash
python -m pytest tests/test_release_verification.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

Run:

```bash
git add scripts/release/run_release_checks.py docs/RELEASE_VERIFICATION.md tests/test_release_verification.py docs/PUBLISH_CHECKLIST.md
git commit -m "test: add release verification tiers"
```

---

### Task 5: Diagnostic bundle and trace surfacing

**Files:**
- Create: `src/mase/diagnostics.py`
- Create: `tests/test_diagnostics.py`
- Modify: `src/mase/models.py`
- Modify: `src/mase/engine.py`
- Modify: `benchmarks/runner.py`
- Modify: `integrations/openai_compat/server.py`
- Modify: `docs/TROUBLESHOOTING.md`

- [ ] **Step 1: Write the failing diagnostics test**

Create `tests/test_diagnostics.py`:

```python
from __future__ import annotations

from pathlib import Path

from mase.diagnostics import build_diagnostic_bundle, classify_error_kind


ROOT = Path(__file__).resolve().parents[1]


def test_classify_error_kind_maps_known_failure_shapes() -> None:
    assert classify_error_kind("Missing API key for provider") == "config_failure"
    assert classify_error_kind("dataset file not found") == "dataset_input_failure"
    assert classify_error_kind("provider timeout while calling model") == "model_backend_failure"
    assert classify_error_kind("publish gate mismatch") == "regression_gate_failure"


def test_build_diagnostic_bundle_keeps_trace_and_profile() -> None:
    payload = build_diagnostic_bundle(
        trace_id="trace-123",
        config_profile="published-local-default",
        surface="benchmark",
        error_kind="config_failure",
        results_path="results/demo.json",
    )

    assert payload["trace_id"] == "trace-123"
    assert payload["config_profile"] == "published-local-default"
    assert payload["surface"] == "benchmark"
    assert payload["error_kind"] == "config_failure"


def test_openai_server_surfaces_trace_header() -> None:
    source = (ROOT / "integrations" / "openai_compat" / "server.py").read_text(encoding="utf-8")
    assert "X-MASE-Trace-Id" in source
    assert "mase_run(" in source
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
python -m pytest tests/test_diagnostics.py -q
```

Expected: FAIL because `mase.diagnostics` does not exist yet and the server does not surface a trace header.

- [ ] **Step 3: Add diagnostic helpers**

Create `src/mase/diagnostics.py`:

```python
from __future__ import annotations

from typing import Any


def classify_error_kind(message: str) -> str:
    text = message.lower()
    if "api key" in text or "config" in text:
        return "config_failure"
    if "dataset" in text or "file not found" in text:
        return "dataset_input_failure"
    if "provider" in text or "timeout" in text or "model" in text:
        return "model_backend_failure"
    return "regression_gate_failure"


def build_diagnostic_bundle(
    *,
    trace_id: str,
    config_profile: str | None,
    surface: str,
    error_kind: str,
    results_path: str = "",
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "config_profile": config_profile,
        "surface": surface,
        "error_kind": error_kind,
        "results_path": results_path,
    }
```

- [ ] **Step 4: Surface trace IDs in public models and benchmark summaries**

Update `src/mase/models.py`:

```python
@dataclass(frozen=True)
class OrchestrationTrace:
    trace_id: str
    route: RouteDecision
    planner: PlannerSnapshot
    thread: ThreadContext
    executor_target: dict[str, Any]
    answer: str
    search_results: list[dict[str, Any]]
    fact_sheet: str
    evidence_assessment: dict[str, Any] | None = None
    record_path: str = ""
```

Update the `OrchestrationTrace(...)` construction in `src/mase/engine.py` to pass:

```python
trace = OrchestrationTrace(
    trace_id=trace_id,
    route=route,
    planner=planner_snapshot,
    thread=thread_context,
    executor_target=executor_target,
    answer=answer,
    search_results=search_results,
    fact_sheet=fact_sheet,
    evidence_assessment=evidence_assessment,
    record_path=record_path,
)
```

Update `benchmarks/runner.py` after `summary["config_profile"] = resolved_profile`:

```python
summary["diagnostic_bundle"] = build_diagnostic_bundle(
    trace_id=run_id,
    config_profile=resolved_profile,
    surface="benchmark",
    error_kind="regression_gate_failure",
    results_path=str(results_path),
)
```

- [ ] **Step 5: Surface the trace header in the OpenAI-compatible server**

Update `integrations/openai_compat/server.py` imports:

```python
from fastapi import FastAPI, Response  # type: ignore
from mase import mase_run  # noqa: E402
```

Update `chat_completions`:

```python
@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest, response: Response) -> Any:
    question = _last_user(req.messages)
    trace = mase_run(question) if question else None
    answer = trace.answer if trace else ""
    if trace:
        response.headers["X-MASE-Trace-Id"] = trace.trace_id
```

For the streaming branch, set the same header:

```python
stream = StreamingResponse(_stream(), media_type="text/event-stream")
if trace:
    stream.headers["X-MASE-Trace-Id"] = trace.trace_id
return stream
```

- [ ] **Step 6: Document the new diagnostic story**

Append to `docs/TROUBLESHOOTING.md`:

```md
## Diagnostic bundle

Benchmark summaries include `diagnostic_bundle`.
OpenAI-compatible responses expose `X-MASE-Trace-Id`.
Use those two surfaces first when explaining why one run differs from another.
```

- [ ] **Step 7: Run the test to verify GREEN**

Run:

```bash
python -m pytest tests/test_diagnostics.py -q
```

Expected: PASS

- [ ] **Step 8: Commit**

Run:

```bash
git add src/mase/diagnostics.py tests/test_diagnostics.py src/mase/models.py src/mase/engine.py benchmarks/runner.py integrations/openai_compat/server.py docs/TROUBLESHOOTING.md
git commit -m "feat: add diagnostic bundle and trace surfacing"
```

---

### Task 6: README headline rerun closure

**Files:**
- Create: `scripts/release/record_readme_rerun.py`
- Create: `docs/release/README_HEADLINE_RUNBOOK.md`
- Create: `tests/test_readme_headline_rerun.py`
- Modify: `docs/release/current/manifest.json`
- Modify: `docs/release/FIX_VALIDATION_LEDGER.md`
- Modify: `README.md`
- Modify: `BENCHMARKS.md`

- [ ] **Step 1: Write the failing rerun-closure test**

Create `tests/test_readme_headline_rerun.py`:

```python
from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_headline_runbook_lists_all_required_commands() -> None:
    text = (ROOT / "docs" / "release" / "README_HEADLINE_RUNBOOK.md").read_text(encoding="utf-8")
    assert "python scripts/benchmarks/run_lveval_256k_batch.py --task factrecall_en --sample-limit 124" in text
    assert "python scripts/benchmarks/run_nolima_mase_smoke.py" in text
    assert "python scripts/benchmarks/run_api_hotswap_longmemeval_batch.py --sample-limit 500" in text


def test_rerun_recorder_builds_expected_payload() -> None:
    module = runpy.run_path(str(ROOT / "scripts" / "release" / "record_readme_rerun.py"))
    payload = module["_build_payload"](
        lveval_path="results/lveval.json",
        nolima_path="results/nolima.json",
        longmemeval_path="results/longmemeval.json",
    )

    assert payload["headline_benchmarks"] == ["lveval", "nolima", "longmemeval"]
    assert payload["artifacts"]["lveval"] == "results/lveval.json"
    assert payload["artifacts"]["nolima"] == "results/nolima.json"
    assert payload["artifacts"]["longmemeval"] == "results/longmemeval.json"
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
python -m pytest tests/test_readme_headline_rerun.py -q
```

Expected: FAIL because the runbook and rerun recorder do not exist yet.

- [ ] **Step 3: Write the rerun runbook and recorder**

Create `docs/release/README_HEADLINE_RUNBOOK.md`:

```md
# README Headline Benchmark Runbook

Run these commands for release closure:

1. `python scripts/benchmarks/run_lveval_256k_batch.py --task factrecall_en --sample-limit 124`
2. `python scripts/benchmarks/run_nolima_mase_smoke.py`
3. `python scripts/benchmarks/run_api_hotswap_longmemeval_batch.py --sample-limit 500`
```

Create `scripts/release/record_readme_rerun.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _build_payload(*, lveval_path: str, nolima_path: str, longmemeval_path: str) -> dict[str, object]:
    return {
        "headline_benchmarks": ["lveval", "nolima", "longmemeval"],
        "artifacts": {
            "lveval": lveval_path,
            "nolima": nolima_path,
            "longmemeval": longmemeval_path,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lveval-path", required=True)
    parser.add_argument("--nolima-path", required=True)
    parser.add_argument("--longmemeval-path", required=True)
    parser.add_argument("--out", default="docs/release/current/readme_headline_rerun.json")
    args = parser.parse_args()

    payload = _build_payload(
        lveval_path=args.lveval_path,
        nolima_path=args.nolima_path,
        longmemeval_path=args.longmemeval_path,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify GREEN**

Run:

```bash
python -m pytest tests/test_readme_headline_rerun.py -q
```

Expected: PASS

- [ ] **Step 5: Execute the README headline reruns**

Run:

```bash
python scripts/benchmarks/run_lveval_256k_batch.py --task factrecall_en --sample-limit 124
python scripts/benchmarks/run_nolima_mase_smoke.py
python scripts/benchmarks/run_api_hotswap_longmemeval_batch.py --sample-limit 500
```

Expected: three fresh result artifacts are produced.

- [ ] **Step 6: Record the rerun artifact bundle**

Use PowerShell to pick the latest generated files, then record them:

```powershell
$lveval = (Get-ChildItem E:\MASE-demo\results\lveval-256k-batch-factrecall_en-*.json | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
$nolima = "E:\MASE-demo\results\nolima\mase-nolima-summary.json"
$longmemeval = (Get-ChildItem E:\MASE-demo\results\longmemeval-cloud-batch-*.json | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
python scripts/release/record_readme_rerun.py --lveval-path $lveval --nolima-path $nolima --longmemeval-path $longmemeval
```

Expected: `docs/release/current/readme_headline_rerun.json` is created.

- [ ] **Step 7: Update bundle, ledger, and public wording with the closure result**

Append to `docs/release/FIX_VALIDATION_LEDGER.md`:

```md
| README headline closure rerun | Re-ran LV-Eval 256k, NoLiMa, and LongMemEval release commands | `python scripts/release/run_release_checks.py --tier publish` + README-headline rerun artifact |
```

Add to `docs/release/current/manifest.json`:

```json
"readme_headline_rerun": "docs/release/current/readme_headline_rerun.json"
```

Add to `README.md`:

```md
Release-closure rerun evidence: `docs/release/current/readme_headline_rerun.json`
```

Add to `BENCHMARKS.md`:

```md
Release-closure rerun evidence lives in `docs/release/current/readme_headline_rerun.json`.
```

- [ ] **Step 8: Run final release verification**

Run:

```bash
python scripts/release/run_release_checks.py --tier publish
```

Expected: PASS

- [ ] **Step 9: Commit**

Run:

```bash
git add scripts/release/record_readme_rerun.py docs/release/README_HEADLINE_RUNBOOK.md tests/test_readme_headline_rerun.py docs/release/current/readme_headline_rerun.json docs/release/current/manifest.json docs/release/FIX_VALIDATION_LEDGER.md README.md BENCHMARKS.md
git commit -m "docs: record README headline rerun closure"
```

---

## Self-Review Checklist

### Spec coverage

- Governed release bundle → Task 1
- Fix-and-validation ledger → Task 2 and Task 6
- Capability statement → Task 2
- Primary supported product path → Task 3
- Quickstart / config / troubleshooting coherence → Task 3
- Smoke / standard / publish release tiers → Task 4
- Operational diagnostics and trace surfacing → Task 5
- README headline benchmark rerun closure → Task 6
- Capability preservation gates remain green → Tasks 4 and 6

### Placeholder scan

- No placeholder markers remain.
- Every task contains exact file paths, commands, and concrete code/doc snippets.

### Type consistency

- Release bundle paths consistently use repo-relative strings under `docs/release/`.
- Supported surface consistently names `examples/10_persistent_chat_cli.py` as the primary quickstart.
- Product-facing integration surface consistently names `integrations/openai_compat/server.py`.
- Diagnostics consistently use `trace_id`, `config_profile`, `surface`, `error_kind`, and `results_path`.
