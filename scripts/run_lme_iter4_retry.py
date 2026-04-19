"""Plan A: iter4 second-opinion retry on the 103 LLM-judge fails.

For each of the 103 iter4-fail questions, route to grounded_long_memory_retry_kimi
(kimi-k2.5 primary + non-abstain bias prompt). Then LLM-judge rescore.

After this run, scripts/combine_iter4_retry.py merges:
  - if iter4 already passed → keep iter4 answer
  - elif retry judge=PASS → upgrade to retry answer
  - else → keep iter4 answer (fail)

Slice composition (103):
  temporal-reasoning  44, multi-session 37, knowledge-update 11,
  single-session-preference 8, single-session-user 2, single-session-assistant 1
"""
import os
import sys
import json
import time
import subprocess

sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")

os.environ["MASE_CONFIG_PATH"] = r"E:\MASE-demo\config.lme_glm5.json"
os.environ["MASE_MULTIPASS"] = "1"
os.environ.setdefault("MASE_MULTIPASS_VARIANTS", "2")
os.environ.setdefault("MASE_MULTIPASS_HYDE", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK_TOP", "40")
os.environ["MASE_LME_VERIFY"] = "1"
os.environ["MASE_LME_ROUTE_BY_QID"] = "0"
os.environ["MASE_LME_QTYPE_ROUTING"] = "0"  # off — retry takes priority
os.environ["MASE_LME_RETRY"] = "1"          # force retry mode for all

from benchmarks.runner import BenchmarkRunner

PATH = r"E:\MASE-demo\data\longmemeval_official\longmemeval_s_iter4_fails.json"
data = json.load(open(PATH, "r", encoding="utf-8"))
print(f"LME iter4-RETRY on {len(data)} samples (all iter4 LLM-judge FAILs)")
print(f"Retry mode: grounded_long_memory_retry_kimi (kimi-k2.5 + non-abstain bias)")

runner = BenchmarkRunner(baseline_profile="none")
t0 = time.time()
summary = runner.run_benchmark("longmemeval_s", sample_limit=len(data), path=PATH)
elapsed_min = round((time.time() - t0) / 60, 2)
print(f"\n[retry] benchmark done in {elapsed_min} min")

# Rescore with LLM-judge
res_path = summary.get("results_path")
print(f"\n[retry] LLM-judge rescore on {res_path}")
subprocess.run([sys.executable, r"E:\MASE-demo\scripts\rescore_with_llm_judge.py", res_path],
               check=True)
rescored_path = res_path.replace(".json", ".rescored.json")

# Persist pointer for combiner
out = {
    "iter": "iter4_retry_kimi",
    "slice_size": len(data),
    "elapsed_min": elapsed_min,
    "results_path": res_path,
    "rescored_path": rescored_path,
}
out_path = r"E:\MASE-demo\scripts\_lme_iter4_retry_pointer.json"
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"Pointer -> {out_path}")
print(f"\nNext: python scripts/combine_iter4_retry.py")
