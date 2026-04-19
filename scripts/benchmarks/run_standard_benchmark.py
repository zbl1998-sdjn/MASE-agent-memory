from __future__ import annotations

import argparse
import json
import sys

try:
    from ._bootstrap import PROJECT_ROOT  # noqa: F401  # bootstrap side-effect: adjusts sys.path
except ImportError:
    from _bootstrap import PROJECT_ROOT  # noqa: F401  # bootstrap side-effect: adjusts sys.path
from benchmarks.registry import list_benchmarks
from benchmarks.runner import BenchmarkRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行标准 benchmark 对比")
    parser.add_argument("--benchmark", type=str, required=True, choices=list_benchmarks(), help="benchmark 名称")
    parser.add_argument("--sample-limit", type=int, default=None, help="样本上限")
    parser.add_argument("--path", type=str, default=None, help="可选数据集 path override")
    parser.add_argument("--config", type=str, default=None, help="可选数据集 config override")
    parser.add_argument("--split", type=str, default=None, help="可选 split override")
    parser.add_argument("--baseline-profile", type=str, default="ollama-qwen25-7b", help="baseline profile")
    parser.add_argument("--baseline-timeout", type=float, default=None, help="baseline 单次请求超时秒数")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    runner = BenchmarkRunner(
        baseline_profile=args.baseline_profile,
        baseline_timeout_seconds=args.baseline_timeout,
    )
    summary = runner.run_benchmark(
        benchmark_name=args.benchmark,
        sample_limit=args.sample_limit,
        path=args.path,
        config=args.config,
        split=args.split,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
