"""Redo the 61 iter4-fails that errored / weren't reached in part1.

Tweaks vs run_lme_iter4_retry.py:
  - MASE_LME_VERIFY=0 (saves 50% kimi calls — we judge-rescore at the end anyway)
  - smaller slice (61 vs 103) → less likely to exhaust quota
  - waits until 19:25 (after GLM 5h cap reset at 19:23:38) before launching
"""
import datetime
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")

# Hold until GLM reset
target = datetime.datetime(2026, 4, 19, 19, 25, 0)
now = datetime.datetime.now()
wait_s = max(0, (target - now).total_seconds())
if wait_s > 0:
    print(f"[redo] waiting {wait_s:.0f}s until {target} (GLM cap reset 19:23:38)")
    time.sleep(wait_s)
print(f"[redo] starting at {datetime.datetime.now()}")

os.environ["MASE_CONFIG_PATH"] = r"E:\MASE-demo\config.lme_glm5.json"
os.environ["MASE_MULTIPASS"] = "1"
os.environ.setdefault("MASE_MULTIPASS_VARIANTS", "2")
os.environ.setdefault("MASE_MULTIPASS_HYDE", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK_TOP", "40")
os.environ["MASE_LME_VERIFY"] = "0"        # off — we judge-rescore at end
os.environ["MASE_LME_ROUTE_BY_QID"] = "0"
os.environ["MASE_LME_QTYPE_ROUTING"] = "0"
os.environ["MASE_LME_RETRY"] = "1"

from benchmarks.runner import BenchmarkRunner

PATH = r"E:\MASE-demo\data\longmemeval_official\longmemeval_s_iter4_fails_redo.json"
data = json.load(open(PATH, encoding="utf-8"))
print(f"[redo] running on {len(data)} samples (errored + unattempted from part1)")

runner = BenchmarkRunner(baseline_profile="none")
t0 = time.time()
summary = runner.run_benchmark("longmemeval_s", sample_limit=len(data), path=PATH)
elapsed_min = round((time.time() - t0) / 60, 2)
print(f"\n[redo] done in {elapsed_min} min")

res_path = summary.get("results_path")
print(f"[redo] LLM-judge rescore on {res_path}")
subprocess.run([sys.executable, r"E:\MASE-demo\scripts\rescore_with_llm_judge.py", res_path], check=True)
rescored_path = res_path.replace(".json", ".rescored.json")

# Save pointer for combiner (now points to BOTH parts)
out = {
    "iter": "iter4_retry_kimi_part2",
    "slice_size": len(data),
    "elapsed_min": elapsed_min,
    "results_path": res_path,
    "rescored_path": rescored_path,
    "part1_results_path": r"E:\MASE-demo\results\iter4_retry_part1.json",
}
json.dump(out, open(r"E:\MASE-demo\scripts\_lme_iter4_retry_pointer.json", "w", encoding="utf-8"),
          indent=2, ensure_ascii=False)
print("Pointer updated. Next: python scripts/combine_iter4_retry.py")
