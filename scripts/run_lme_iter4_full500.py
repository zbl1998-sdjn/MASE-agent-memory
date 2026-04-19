"""LME iter4: ablation config (NO routing, default verifier on every question)
applied to the FULL 500-sample official LongMemEval set.

Why this run:
- iter3 dev_250 ablation (routing OFF) achieved 200/250 = 80.0% LLM-judge.
- iter2 baseline on full_500 was 80.2%.
- This run validates apples-to-apples: same config as ablation, but on full_500
  instead of dev_250. Gives us the authoritative iter4 publish-candidate number
  on the full official split.

Config:
- config.lme_glm5.json (GLM-5 executor + kimi-k2.5 verifier + glm-4.6 fallback)
- multipass on (HyDE + 2 query variants + rerank top 40)
- MASE_LME_VERIFY=1 (universal verifier)
- MASE_LME_ROUTE_BY_QID=0 (NO bucket-aware routing — was the iter3 regressor)

Output:
- scripts/_lme_iter4_full500_summary.json
- results/benchmark-longmemeval_s-haystack-<ts>.json (run by runner)

Cost note: ~80 min wall-clock, kimi+glm cloud calls only.
Per user rule: deepseek = lowest priority; minimax/glm/kimi/qwen first.
Current chain: kimi-k2.5 -> deepseek-chat (will be reordered if regression).
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
os.environ["MASE_LME_ROUTE_BY_QID"] = "0"  # iter4: routing OFF (matches winning ablation)

from benchmarks.runner import BenchmarkRunner

PATH = r"E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json"
data = json.load(open(PATH, "r", encoding="utf-8"))
total_n = len(data)
print(f"LME iter4 (FULL-500, no-routing ablation config) on {total_n} samples")

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
    "iter": "iter4",
    "split": "full_500",
    "route_by_qid": False,
    "multipass": "on",
    "verifier": "kimi-k2.5 (default universal, no routing)",
    "executor": "glm-5-cloud",
    "n": n,
    "pass_substring": p,
    "pct_substring": pct,
    "elapsed_min": elapsed_min,
    "results_path": summary.get("results_path"),
}
out_path = r"E:\MASE-demo\scripts\_lme_iter4_full500_summary.json"
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"iter4 full_500: {p}/{n} = {pct}% substring [{elapsed_min}min]")
print(f"Summary -> {out_path}")
print(f"Next: rescore_with_llm_judge.py {summary.get('results_path')}")
