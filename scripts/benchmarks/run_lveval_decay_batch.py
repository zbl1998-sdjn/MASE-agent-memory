from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

try:
    from ._bootstrap import PROJECT_ROOT
except ImportError:
    from _bootstrap import PROJECT_ROOT
from summarize_benchmark_result import summarize_benchmark_file

from benchmarks.runner import BenchmarkRunner

BASE_DIR = PROJECT_ROOT
RESULTS_DIR = BASE_DIR / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量运行 LV-Eval 多长度档位并输出衰减曲线统计")
    parser.add_argument("--task", type=str, default="factrecall_zh", help="LV-Eval 任务前缀，例如 factrecall_zh")
    parser.add_argument("--lengths", type=str, default="16k,32k,64k", help="逗号分隔的长度档位")
    parser.add_argument("--sample-limit", type=int, default=10, help="每个长度档位抽样数")
    parser.add_argument("--baseline-profile", type=str, default="ollama-qwen25-7b", help="baseline profile")
    parser.add_argument("--baseline-timeout", type=float, default=180, help="baseline 单次请求超时秒数")
    return parser.parse_args()


def build_length_entry(config_name: str, benchmark_summary: dict[str, Any]) -> dict[str, Any]:
    aggregate = summarize_benchmark_file(benchmark_summary["results_path"])
    results = benchmark_summary.get("results") or []
    lengths = [((item.get("sample_metadata") or {}).get("length")) for item in results]
    return {
        "config": config_name,
        "sample_limit": len(results),
        "length_values": lengths,
        "benchmark_results_path": benchmark_summary["results_path"],
        "aggregate": aggregate,
    }


def main() -> None:
    args = parse_args()
    lengths = [item.strip() for item in args.lengths.split(",") if item.strip()]
    runner = BenchmarkRunner(
        baseline_profile=args.baseline_profile,
        baseline_timeout_seconds=args.baseline_timeout,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    per_length: list[dict[str, Any]] = []
    for length in lengths:
        config_name = f"{args.task}_{length}"
        summary = runner.run_benchmark(
            benchmark_name="lveval",
            config=config_name,
            sample_limit=args.sample_limit,
        )
        per_length.append(build_length_entry(config_name, summary))

    consolidated: dict[str, Any] = {
        "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "task": args.task,
        "lengths": lengths,
        "sample_limit": args.sample_limit,
        "baseline_profile": args.baseline_profile,
        "baseline_timeout": args.baseline_timeout,
        "results": per_length,
    }
    output_path = RESULTS_DIR / f"lveval-decay-batch-{args.task}-{consolidated['run_id']}.json"
    output_path.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2), encoding="utf-8")
    consolidated["results_path"] = str(output_path)
    print(json.dumps(consolidated, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
