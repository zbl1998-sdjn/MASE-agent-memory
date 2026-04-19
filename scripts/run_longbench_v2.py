"""LongBench-v2 runner for MASE.

Usage:
    python scripts/run_longbench_v2.py --length short --limit 20 --gpu 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--length", default="short", choices=["short", "medium", "long", "all"])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--gpu", default=None, help="CUDA_VISIBLE_DEVICES override")
    parser.add_argument("--out", default=str(ROOT / "scripts" / "_longbench_v2_summary.json"))
    args = parser.parse_args()

    if args.gpu is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
    os.environ.setdefault("MASE_CONFIG_PATH", args.config)
    # LongBench-v2 is a regular MC reasoning benchmark (NOT adversarial like LV-Eval factrecall).
    # Route the executor to the MC-tuned reasoning prompt + deepseek-r1:7b.
    os.environ.setdefault("MASE_LONG_CONTEXT_VARIANT", "mc")

    from benchmarks.runner import BenchmarkRunner

    runner = BenchmarkRunner(sample_retry_count=0, baseline_profile="off")
    cfg_arg = None if args.length == "all" else args.length
    started = time.perf_counter()
    summary = runner.run_benchmark(
        "longbench_v2", sample_limit=args.limit, config=cfg_arg
    )
    elapsed = time.perf_counter() - started
    sb = summary["scoreboard"]
    n = sb.get("mase_completed_count", 0)
    p = sb.get("mase_pass_count", 0)
    pct = round(100 * p / max(1, n), 2)
    out_summary = {
        "benchmark": "longbench_v2",
        "length_filter": args.length,
        "limit": args.limit,
        "completed": n,
        "passed": p,
        "pass_rate_pct": pct,
        "wall_clock_seconds": round(elapsed, 2),
    }
    Path(args.out).write_text(
        json.dumps(out_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[longbench_v2] DONE pass_rate={pct}% ({p}/{n}) elapsed={elapsed:.1f}s -> {args.out}",
        flush=True,
    )


if __name__ == "__main__":
    main()
