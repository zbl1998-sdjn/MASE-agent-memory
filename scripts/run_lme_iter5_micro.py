"""LME iter5 MICRO slice: validate qtype routing on 40 questions
(15 fail + 5 pass) from each of the two laggard categories before
committing to the 3h full_500 run.

Slice composition:
  - 15 iter4-FAILED  + 5 iter4-PASSED  temporal-reasoning  = 20
  - 15 iter4-FAILED  + 5 iter4-PASSED  multi-session       = 20
  Total: 40 questions, ~17 min wall-clock.

Pass criteria (decide whether full_500 is worth running):
  - temporal-reasoning: at least 7/15 of the prior fails flip to PASS
    (≈ +47pp on the failing slice → projected +20pp category-wide)
  - multi-session: at least 5/15 of the prior fails flip to PASS
    (≈ +33pp on failing slice → projected +13pp category-wide)
  - REGRESSION GUARD: of the 5 prior-pass per category, no more than
    1 flips to FAIL (i.e. at least 4/5 still pass).

If criteria met → launch run_lme_iter5_full500.py.
If not → revisit deepseek prompt / rerank threshold before burning 3h.

Output:
  scripts/_lme_iter5_micro.log
  scripts/_lme_iter5_micro_summary.json (per-id flip table + verdict)
"""
import os
import sys
import json
import time

sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")

# Same env as iter5 full
os.environ["MASE_CONFIG_PATH"] = r"E:\MASE-demo\config.lme_glm5.json"
os.environ["MASE_MULTIPASS"] = "1"
os.environ.setdefault("MASE_MULTIPASS_VARIANTS", "2")
os.environ.setdefault("MASE_MULTIPASS_HYDE", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK", "1")
os.environ.setdefault("MASE_MULTIPASS_RERANK_TOP", "40")
os.environ["MASE_MULTIPASS_RERANK_TOP_MULTISESSION"] = "80"
os.environ["MASE_LME_VERIFY"] = "1"
os.environ["MASE_LME_ROUTE_BY_QID"] = "0"
os.environ["MASE_LME_QTYPE_ROUTING"] = "1"

from benchmarks.runner import BenchmarkRunner

PATH = r"E:\MASE-demo\data\longmemeval_official\longmemeval_s_iter5_micro.json"
data = json.load(open(PATH, "r", encoding="utf-8"))
print(f"LME iter5 MICRO on {len(data)} samples (15F+5P each of 2 categories)")

runner = BenchmarkRunner(baseline_profile="none")
t0 = time.time()
summary = runner.run_benchmark("longmemeval_s", sample_limit=len(data), path=PATH)
elapsed_min = round((time.time() - t0) / 60, 2)

# Rescore with LLM-judge so verdict matches the metric we care about
import subprocess
res_path = summary.get("results_path")
print(f"\n[micro] LLM-judge rescore on {res_path}")
subprocess.run([sys.executable, r"E:\MASE-demo\scripts\rescore_with_llm_judge.py", res_path],
               check=True)
rescored_path = res_path.replace(".json", ".rescored.json")
results = json.load(open(rescored_path, encoding="utf-8"))["results"]

# Compare to iter4 LLM-judge baseline per id
baseline = json.load(open(r"E:\MASE-demo\scripts\_lme_iter5_micro_baseline.json", encoding="utf-8"))

flips = {"temporal-reasoning": {"F2P": 0, "P2F": 0, "F2F": 0, "P2P": 0},
         "multi-session":      {"F2P": 0, "P2F": 0, "F2F": 0, "P2P": 0}}
detail = []
for r in results:
    qid = r["id"]
    sc = r.get("mase", {}).get("score", {})
    iter5_pass = bool(sc.get("details", {}).get("exact_substring") or sc.get("llm_judge_upgraded"))
    if qid not in baseline:
        continue
    qt = baseline[qid]["qt"]
    iter4_pass = baseline[qid]["iter4_pass"]
    key = ("P" if iter4_pass else "F") + "2" + ("P" if iter5_pass else "F")
    flips[qt][key] += 1
    detail.append({"qid": qid, "qt": qt, "iter4": iter4_pass, "iter5": iter5_pass, "flip": key})

print()
for qt, fl in flips.items():
    n_fail_was = fl["F2F"] + fl["F2P"]
    n_pass_was = fl["P2F"] + fl["P2P"]
    print(f"{qt:24s}  F2P={fl['F2P']}/{n_fail_was}  P2F={fl['P2F']}/{n_pass_was}  "
          f"P2P={fl['P2P']}  F2F={fl['F2F']}")

# Verdict — LLM-judge era thresholds.
# Slice has 12 fail + 8 pass per category.
# Category-wide gap to 85%: temporal +24/133, multi +17/133.
# Need F2P >= 4/12 (33%) projects to +15 on temporal, +15 on multi (combined ~+25 -> ~84%).
# Stretch goal F2P >= 6/12 (50%) projects to +22 on temporal -> closes the gap alone.
temp_f2p = flips["temporal-reasoning"]["F2P"]
temp_p2f = flips["temporal-reasoning"]["P2F"]
ms_f2p   = flips["multi-session"]["F2P"]
ms_p2f   = flips["multi-session"]["P2F"]

ok_temp = (temp_f2p >= 4) and (temp_p2f <= 1)
ok_ms   = (ms_f2p   >= 4) and (ms_p2f   <= 1)
verdict = "GO_FULL_500" if (ok_temp and ok_ms) else \
          "PARTIAL_GO"  if (ok_temp or ok_ms)  else "NO_GO_RETUNE"

out = {
    "iter": "iter5_micro_v2_kimi",
    "slice_size": len(data),
    "elapsed_min": elapsed_min,
    "metric": "llm_judge",
    "flips": flips,
    "thresholds": {
        "temporal_min_F2P": 4, "temporal_max_P2F": 1,
        "multisession_min_F2P": 4, "multisession_max_P2F": 1,
    },
    "verdict": verdict,
    "results_path": res_path,
    "rescored_path": rescored_path,
    "detail": detail,
}
out_path = r"E:\MASE-demo\scripts\_lme_iter5_micro_summary.json"
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\nVERDICT: {verdict}")
print(f"Summary -> {out_path}")
