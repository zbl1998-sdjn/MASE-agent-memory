"""Run a tiny subset of LV-Eval to validate the long_context_qa fix."""
import argparse
import json
import os
import sys

sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")
os.environ.setdefault("MASE_CONFIG_PATH", r"E:\MASE-demo\config.json")

from benchmarks.runner import BenchmarkRunner

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="factrecall_zh_64k")
parser.add_argument("--limit", type=int, default=10)
parser.add_argument("--benchmark", default="lveval")
args = parser.parse_args()

runner = BenchmarkRunner(sample_retry_count=0, baseline_profile="off")
summary = runner.run_benchmark(args.benchmark, sample_limit=args.limit, config=args.config if args.benchmark=="lveval" else None)
print("DONE", args.config)
print("scoreboard:", json.dumps(summary["scoreboard"], ensure_ascii=False))
print("results_path:", summary.get("memory_dir"))
