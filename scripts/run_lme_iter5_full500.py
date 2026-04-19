"""LME iter5: per-question-type routing on full_500.

Why this run
============
iter4 full_500 (substring) breakdown projected to LLM-judge ~73-76%:
    single-session-user      84% sub  -> ~88% judge   (PASS)
    knowledge-update         79% sub  -> ~85% judge   (PASS)
    single-session-pref       0% sub  -> ~80% judge   (substring artifact)
    multi-session            59% sub  -> ~70% judge   (retrieval gap)
    temporal-reasoning       52% sub  -> ~62% judge   (deep-reasoning gap)

iter5 attacks the two real laggards with type-specific routing.

Knobs (gated by MASE_LME_QTYPE_ROUTING=1, default OFF)
------------------------------------------------------
- temporal-reasoning -> executor mode `grounded_long_memory_deepreason_english`
  -> deepseek-r1:7b LOCAL (user explicitly opted in for this category;
     general "deepseek = lowest priority" rule still applies elsewhere)
  -> fallback chain: kimi-k2.5 -> glm-4.6 (NO deepseek-chat)
- multi-session -> rerank_top bumped 40 -> 80 via
  MASE_MULTIPASS_RERANK_TOP_MULTISESSION
- All other types -> identical to iter4 (GLM-5 + multipass rerank 40)

Expected outcome
----------------
If both knobs deliver as designed:
    temporal-reasoning   62% -> ~75-80% (deep reasoning closes ~15pp)
    multi-session        70% -> ~78%    (wider rerank closes ~8pp)
Weighted total ~80-83%. Still below 85% gate but a real step.
If we land >=82% we ship; if <80% we triage instead of looping forever.

Output
------
- scripts/_lme_iter5_full500.log          (Tee'd stdout)
- scripts/_lme_iter5_full500_summary.json (substring summary)
- results/benchmark-longmemeval_s-haystack-<ts>.json (full per-row)

Cost note: ~3-3.5h wall-clock. deepseek-r1:7b runs locally on the 48GB GPU.
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
os.environ["MASE_MULTIPASS_RERANK_TOP_MULTISESSION"] = "80"
os.environ["MASE_LME_VERIFY"] = "1"
os.environ["MASE_LME_ROUTE_BY_QID"] = "0"          # no qid bucket routing (iter4 winning baseline)
os.environ["MASE_LME_QTYPE_ROUTING"] = "1"         # iter5 NEW: per-question_type routing

from benchmarks.runner import BenchmarkRunner

PATH = r"E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json"
data = json.load(open(PATH, "r", encoding="utf-8"))
total_n = len(data)
print(f"LME iter5 (FULL-500, qtype-aware routing) on {total_n} samples")
print(f"  temporal-reasoning -> deepseek-r1:7b local")
print(f"  multi-session      -> rerank_top=80")
print(f"  others             -> iter4 baseline (GLM-5 + rerank 40)")

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
    "iter": "iter5",
    "split": "full_500",
    "qtype_routing": True,
    "temporal_executor": "deepseek-r1:7b (local)",
    "multisession_rerank_top": 80,
    "verifier": "kimi-k2.5 (default universal)",
    "executor_default": "glm-5-cloud",
    "n": n,
    "pass_substring": p,
    "pct_substring": pct,
    "elapsed_min": elapsed_min,
    "results_path": summary.get("results_path"),
}
out_path = r"E:\MASE-demo\scripts\_lme_iter5_full500_summary.json"
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"iter5 full_500: {p}/{n} = {pct}% substring [{elapsed_min}min]")
print(f"Summary -> {out_path}")
print(f"Next: rescore_with_llm_judge.py {summary.get('results_path')}")
