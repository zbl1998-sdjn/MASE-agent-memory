from __future__ import annotations

import argparse
import json
from datetime import datetime

try:
    from ._bootstrap import PROJECT_ROOT
except ImportError:
    from _bootstrap import PROJECT_ROOT
from summarize_benchmark_result import summarize_benchmark_file

from benchmarks.runner import BenchmarkRunner

BASE_DIR = PROJECT_ROOT
RESULTS_DIR = BASE_DIR / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 LV-Eval 256k 单档测试并输出结构化汇总")
    parser.add_argument("--task", type=str, default="factrecall_zh", help="LV-Eval 任务前缀，例如 factrecall_zh")
    parser.add_argument("--sample-limit", type=int, default=10, help="256k 档位抽样数")
    parser.add_argument("--baseline-profile", type=str, default="ollama-qwen25-7b", help="baseline profile；传 none 可跳过 baseline")
    parser.add_argument("--baseline-timeout", type=float, default=180, help="baseline 单次请求超时秒数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_name = f"{args.task}_256k"
    runner = BenchmarkRunner(
        baseline_profile=args.baseline_profile,
        baseline_timeout_seconds=args.baseline_timeout,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary = runner.run_benchmark(
        benchmark_name="lveval",
        config=config_name,
        sample_limit=args.sample_limit,
    )
    aggregate = summarize_benchmark_file(summary["results_path"])
    consolidated = {
        "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "task": args.task,
        "config": config_name,
        "sample_limit": args.sample_limit,
        "baseline_profile": args.baseline_profile,
        "baseline_timeout": args.baseline_timeout,
        "benchmark_results_path": summary["results_path"],
        "aggregate": aggregate,
    }
    output_path = RESULTS_DIR / f"lveval-256k-batch-{args.task}-{consolidated['run_id']}.json"
    output_path.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2), encoding="utf-8")
    consolidated["results_path"] = str(output_path)
    print(json.dumps(consolidated, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
