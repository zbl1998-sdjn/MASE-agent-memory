"""LME iter3: type-aware verifier routing on DEV-250 split.

Hypotheses (all env-gated, default OFF):
  H1: regular bucket regressed in iter2 (70.4 → 69.6%). Skip verifier for
      regular → recover ~+3pp.
  H2: abstention bucket 3.3% (29 fails, 21 semantically correct but mismatched
      template). New prompt outputs exact GT template
      "You did not mention this information. You mentioned X but not Y." → +4-5pp.
  H3: gpt4_gen bucket 47.1% (abstract multi-step). New CoT verifier enforces
      decompose → evidence → temporal-sort → compute → +4-8pp.

Target:
  - iter2 baseline: 61.0% on full 500
  - iter3 dev_250 target: >=75% (proves hypothesis stack works)
  - if dev passes → ONE shot on test_250 for publish-ready number

Safety:
  - Runs on lme_dev_250 only (250 samples). test_250 FROZEN.
  - No changes to LV-Eval paths. Historical qid-bucket routing is disabled
    because it overfits LongMemEval naming conventions.
"""
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

os.environ["MASE_CONFIG_PATH"] = str(REPO / "config.lme_glm5.json")
os.environ["MASE_MULTIPASS"] = "1"
os.environ.setdefault("MASE_MULTIPASS_VARIANTS", "2")
os.environ.setdefault("MASE_MULTIPASS_HYDE", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK_TOP", "40")
os.environ["MASE_LME_VERIFY"] = "1"
# qid-bucket routing disabled: use general qtype routing instead.
os.environ["MASE_LME_ROUTE_BY_QID"] = "0"

from benchmarks.runner import BenchmarkRunner

PATH = REPO / "data" / "longmemeval_official" / "lme_dev_250.json"
data = json.loads(PATH.read_text(encoding="utf-8"))
total_n = len(data)
print(f"LME iter3 (DEV-250): type-aware verifier on {total_n} samples")

runner = BenchmarkRunner(baseline_profile="none")
t0 = time.time()
summary = runner.run_benchmark("longmemeval_s", sample_limit=total_n, path=str(PATH))
sb = summary["scoreboard"]
n = sb.get("mase_completed_count", 0)
p = sb.get("mase_pass_count", 0)
pct = round(100 * p / max(1, n), 2)
elapsed_min = round((time.time() - t0) / 60, 2)
out = {
    "benchmark": "longmemeval_s",
    "iter": "iter3",
    "split": "dev_250",
    "route_by_qid": False,
    "multipass": "on",
    "verifier": "kimi-k2.5 (generic LME verifier)",
    "executor": "glm-5-cloud",
    "n": n,
    "pass": p,
    "pct": pct,
    "elapsed_min": elapsed_min,
}
(REPO / "scripts" / "_lme_iter3_dev_summary.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"LME iter3 (dev_250): {p}/{n} = {pct}% [{elapsed_min}min]")
print("iter3 success bar: dev >= 75% → proceed to test_250 ONE shot.")
