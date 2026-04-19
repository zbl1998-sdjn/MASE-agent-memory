from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import mean

from test_randomized_recall import run_randomized_recall

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="多 seed 随机回忆统计")
    parser.add_argument("--rounds", type=int, default=20, help="每个 seed 的随机轮数")
    parser.add_argument(
        "--seeds",
        type=str,
        default="20260410,20260411,20260412",
        help="逗号分隔的随机种子列表",
    )
    parser.add_argument("--config", type=str, default=None, help="可选配置文件路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seeds = [int(item.strip()) for item in args.seeds.split(",") if item.strip()]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    runs = [run_randomized_recall(rounds=args.rounds, seed=seed, config=args.config, persist=True) for seed in seeds]
    per_seed = []
    for run in runs:
        filler_rounds = max(1, int(run["checks"]["filler_rounds"]))
        false_positive_count = int(run["checks"]["false_positive_search_memory_count"])
        per_seed.append(
            {
                "seed": run["seed"],
                "run_id": run["run_id"],
                "results_path": run["results_path"],
                "target_fact_id": run["recall_test"]["target_fact_id"],
                "recall_success": run["checks"]["recall_answer_matched"],
                "false_positive_count": false_positive_count,
                "false_positive_rate": round(false_positive_count / filler_rounds, 4),
            }
        )

    aggregate = {
        "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "rounds_per_seed": args.rounds,
        "seed_count": len(seeds),
        "seeds": seeds,
        "config": args.config or "default",
        "recall_success_count": sum(1 for item in per_seed if item["recall_success"]),
        "recall_success_rate": round(sum(1 for item in per_seed if item["recall_success"]) / max(1, len(per_seed)), 4),
        "avg_false_positive_count": round(mean(item["false_positive_count"] for item in per_seed), 4),
        "avg_false_positive_rate": round(mean(item["false_positive_rate"] for item in per_seed), 4),
        "per_seed": per_seed,
    }

    results_path = RESULTS_DIR / f"randomized-recall-multiseed-{aggregate['run_id']}.json"
    results_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    aggregate["results_path"] = str(results_path)
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
