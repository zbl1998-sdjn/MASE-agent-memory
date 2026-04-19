"""Survey LV-Eval pass rates across all task types and depths.

Usage:
    python scripts/survey_lveval.py --depths 16k --limit 6
    python scripts/survey_lveval.py --depths 16k 64k --limit 6 --out survey.json
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")
os.environ.setdefault("MASE_CONFIG_PATH", r"E:\MASE-demo\config.json")

from benchmarks.runner import BenchmarkRunner

TASKS = [
    "dureader_mixup",
    "hotpotwikiqa_mixup",
    "multifieldqa_en_mixup",
    "multifieldqa_zh_mixup",
    "lic_mixup",
    "loogle_SD_mixup",
    "loogle_CR_mixup",
    "loogle_MIR_mixup",
    "factrecall_en",
    "factrecall_zh",
    "cmrc_mixup",
]

parser = argparse.ArgumentParser()
parser.add_argument("--depths", nargs="+", default=["16k"])
parser.add_argument("--limit", type=int, default=6)
parser.add_argument("--tasks", nargs="*", default=None, help="Subset of tasks; default all")
parser.add_argument("--out", default=r"E:\MASE-demo\scripts\_survey_results.json")
args = parser.parse_args()

tasks = args.tasks if args.tasks else TASKS
results: list[dict] = []
runner = BenchmarkRunner(sample_retry_count=0, baseline_profile="off")

for depth in args.depths:
    for task in tasks:
        config = f"{task}_{depth}"
        print(f"\n>>> {config}", flush=True)
        t0 = time.perf_counter()
        try:
            summary = runner.run_benchmark("lveval", sample_limit=args.limit, config=config)
            sb = summary["scoreboard"]
            row = {
                "config": config,
                "task": task,
                "depth": depth,
                "n": sb["mase_completed_count"],
                "pass": sb["mase_pass_count"],
                "score": sb["mase_avg_score"],
                "wall": round(time.perf_counter() - t0, 1),
                "avg_case": sb["mase_avg_wall_clock_seconds"],
            }
        except Exception as e:
            row = {
                "config": config,
                "task": task,
                "depth": depth,
                "error": f"{type(e).__name__}: {e}",
            }
        results.append(row)
        print(f"<<< {config}: {row}", flush=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

print("\n=== SURVEY DONE ===")
for r in results:
    if "error" in r:
        print(f"  {r['config']:<40} ERROR {r['error']}")
    else:
        print(f"  {r['config']:<40} {r['pass']:>2}/{r['n']:<2} = {100*r['pass']/max(1,r['n']):5.1f}%  (avg {r['avg_case']:.1f}s)")
