from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

try:
    from ._bootstrap import PROJECT_ROOT
except ImportError:
    from _bootstrap import PROJECT_ROOT
from benchmarks.runner import BenchmarkRunner

BASE_DIR = PROJECT_ROOT
RESULTS_DIR = BASE_DIR / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 LV-Eval 长上下文长度分档对比")
    parser.add_argument("--task", type=str, default="factrecall_zh", help="LV-Eval 任务前缀，例如 factrecall_zh")
    parser.add_argument("--lengths", type=str, default="16k,32k,64k", help="逗号分隔的长度档位")
    parser.add_argument("--sample-limit", type=int, default=1, help="每个长度档位抽样数")
    parser.add_argument("--baseline-profile", type=str, default="ollama-qwen25-7b", help="baseline profile")
    parser.add_argument("--baseline-timeout", type=float, default=None, help="baseline 单次请求超时秒数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runner = BenchmarkRunner(
        baseline_profile=args.baseline_profile,
        baseline_timeout_seconds=args.baseline_timeout,
    )
    lengths = [item.strip() for item in args.lengths.split(",") if item.strip()]
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    sweep_results = []
    for length in lengths:
        config_name = f"{args.task}_{length}"
        summary = runner.run_benchmark(
            benchmark_name="lveval",
            config=config_name,
            sample_limit=args.sample_limit,
        )
        sweep_results.append(
            {
                "config": config_name,
                "length": length,
                "sample_limit": args.sample_limit,
                "benchmark_results_path": summary["results_path"],
                "scoreboard": summary["scoreboard"],
                "sample_lengths": [item.get("sample_metadata", {}).get("length") for item in summary["results"]],
            }
        )

    consolidated = {
        "run_id": run_id,
        "task": args.task,
        "lengths": lengths,
        "sample_limit": args.sample_limit,
        "baseline_profile": args.baseline_profile,
        "baseline_timeout": args.baseline_timeout,
        "results": sweep_results,
    }
    consolidated["results_path"] = str(RESULTS_DIR / f"lveval-context-sweep-{args.task}-{run_id}.json")
    Path(consolidated["results_path"]).write_text(json.dumps(consolidated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(consolidated, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
