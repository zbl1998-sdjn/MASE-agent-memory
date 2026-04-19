"""LME iter3 ablation: turn OFF type-aware verifier routing (regression test).

Hypothesis under test:
  iter3 dev_250 substring=52% / LLM-judge=68.4% is BELOW iter2 expectation.
  Sole config diff vs iter2 is MASE_LME_ROUTE_BY_QID=1 (per-bucket verifier
  routing: regular skips verifier, abstention uses template normalization,
  gpt4_gen uses CoT verifier).

  This run sets MASE_LME_ROUTE_BY_QID=0 (default verifier on every question,
  matching iter2 behavior) on the SAME dev_250 split. Result decides:

  - If THIS run >> iter3-full (substring or judge) → routing IS the regression.
    Action: revisit per-bucket logic (probably the `regular` skip-verifier
    branch is dropping correct answers it shouldn't).

  - If THIS run ~= iter3-full → dev_250 is just harder than full_500.
    Action: build a better verifier from scratch; routing is not the problem.

Output: scripts/_lme_iter3_ABLATION_noroute_summary.json
"""
import os
import sys
import json
import time

sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")

os.environ["MASE_CONFIG_PATH"] = r"E:\MASE-demo\config.lme_glm5.json"
os.environ["MASE_MULTIPASS"] = "1"
os.environ.setdefault("MASE_MULTIPASS_VARIANTS", "2")
os.environ.setdefault("MASE_MULTIPASS_HYDE", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK_TOP", "40")
os.environ["MASE_LME_VERIFY"] = "1"
# ABLATION: routing OFF — every question uses default verifier
os.environ["MASE_LME_ROUTE_BY_QID"] = "0"

from benchmarks.runner import BenchmarkRunner

PATH = r"E:\MASE-demo\data\longmemeval_official\lme_dev_250.json"
data = json.load(open(PATH, "r", encoding="utf-8"))
total_n = len(data)
print(f"LME iter3 ABLATION (no routing) on dev_250: {total_n} samples")

runner = BenchmarkRunner(baseline_profile="none")
t0 = time.time()
summary = runner.run_benchmark("longmemeval_s", sample_limit=total_n, path=PATH)
sb = summary["scoreboard"]
n = sb.get("mase_completed_count", 0)
p = sb.get("mase_pass_count", 0)
pct = round(100 * p / max(1, n), 2)
elapsed_min = round((time.time() - t0) / 60, 2)
out = {
    "benchmark": "longmemeval_s",
    "iter": "iter3-ablation-noroute",
    "split": "dev_250",
    "route_by_qid": False,
    "multipass": "on",
    "verifier": "kimi-k2.5 (default only, no routing)",
    "executor": "glm-5-cloud",
    "n": n,
    "pass": p,
    "pct_substring": pct,
    "elapsed_min": elapsed_min,
    "results_path": summary.get("results_path"),
}
json.dump(
    out,
    open(r"E:\MASE-demo\scripts\_lme_iter3_ABLATION_noroute_summary.json", "w", encoding="utf-8"),
    ensure_ascii=False, indent=2,
)
print(f"ABLATION done: {p}/{n} = {pct}% substring [{elapsed_min}min]")
print("Run rescore_with_llm_judge.py on the result for LLM-judge comparison.")
