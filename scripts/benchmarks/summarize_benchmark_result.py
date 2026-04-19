from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import PROJECT_ROOT
except ImportError:
    from _bootstrap import PROJECT_ROOT

BASE_DIR = PROJECT_ROOT
RESULTS_DIR = BASE_DIR / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="汇总 benchmark 结果中的通过率、超时率与错误类型")
    parser.add_argument("--path", type=str, required=True, help="benchmark 结果 JSON 路径")
    parser.add_argument("--output", type=str, default=None, help="可选输出路径")
    return parser.parse_args()


def load_summary(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve_side(item: dict[str, Any], side_key: str) -> dict[str, Any]:
    if side_key == "baseline":
        return (item.get("baseline") or item.get("qwen27b") or {})
    return item.get(side_key) or {}


def classify_side_result(item: dict[str, Any], side_key: str) -> str:
    side = _resolve_side(item, side_key)
    error = str(side.get("error") or "").strip()
    error_kind = str(side.get("error_kind") or "").strip()
    answer = str(side.get("answer") or "").strip()

    if error_kind == "skipped":
        return "skipped"
    if error_kind == "infra_error":
        return "infra_error"
    if error_kind == "execution_error":
        return "error"
    if error:
        lowered = error.lower()
        if "connectionerror" in lowered or "connecterror" in lowered or "failed to connect to ollama" in lowered:
            return "infra_error"
        if "connection reset" in lowered or "connection aborted" in lowered or "server disconnected" in lowered:
            return "infra_error"
        if "503" in lowered or "502" in lowered or "504" in lowered:
            return "infra_error"
        if "readtimeout" in lowered or "timed out" in lowered or "timeout" in lowered:
            return "infra_error"
        return "error"
    if not answer:
        return "empty_answer"
    score = (side.get("score") or {}).get("all_matched")
    if bool(score):
        return "matched"
    return "mismatch"


def side_elapsed_seconds(item: dict[str, Any], side_key: str) -> float:
    side = _resolve_side(item, side_key)
    metrics = side.get("metrics") or {}
    if side_key == "mase":
        return float(metrics.get("wall_clock_seconds") or 0.0)
    return float(metrics.get("elapsed_seconds") or 0.0)


def summarize_side(results: list[dict[str, Any]], side_key: str) -> dict[str, Any]:
    outcome_counts = Counter(classify_side_result(item, side_key) for item in results)
    sample_count = len(results)
    scores = [float(((_resolve_side(item, side_key).get("score") or {}).get("score")) or 0.0) for item in results]
    elapsed_values = [side_elapsed_seconds(item, side_key) for item in results]
    non_zero_elapsed = [value for value in elapsed_values if value > 0]

    return {
        "sample_count": sample_count,
        "pass_count": sum(1 for item in results if bool((_resolve_side(item, side_key).get("score") or {}).get("all_matched"))),
        "avg_score": round(sum(scores) / max(1, sample_count), 4),
        "completed_count": outcome_counts.get("matched", 0) + outcome_counts.get("mismatch", 0),
        "infra_error_count": outcome_counts.get("infra_error", 0),
        "empty_answer_count": outcome_counts.get("empty_answer", 0),
        "other_error_count": outcome_counts.get("error", 0),
        "skipped_count": outcome_counts.get("skipped", 0),
        "completion_rate": round(
            (outcome_counts.get("matched", 0) + outcome_counts.get("mismatch", 0)) / max(1, sample_count),
            4,
        ),
        "pass_rate_on_completed": round(
            sum(1 for item in results if bool((_resolve_side(item, side_key).get("score") or {}).get("all_matched")))
            / max(1, outcome_counts.get("matched", 0) + outcome_counts.get("mismatch", 0)),
            4,
        ),
        "infra_error_rate": round(outcome_counts.get("infra_error", 0) / max(1, sample_count), 4),
        "avg_elapsed_seconds": round(sum(non_zero_elapsed) / max(1, len(non_zero_elapsed)), 4) if non_zero_elapsed else 0.0,
        "outcome_counts": dict(outcome_counts),
    }


def build_per_sample_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        rows.append(
            {
                "id": item.get("id"),
                "length": ((item.get("sample_metadata") or {}).get("length")),
                "ground_truth": item.get("ground_truth"),
                "mase_outcome": classify_side_result(item, "mase"),
                "baseline_outcome": classify_side_result(item, "baseline"),
                "mase_answer": ((item.get("mase") or {}).get("answer") or "")[:160],
                "baseline_answer": (_resolve_side(item, "baseline").get("answer") or "")[:160],
                "mase_error": (item.get("mase") or {}).get("error"),
                "baseline_error": _resolve_side(item, "baseline").get("error"),
                "mase_error_kind": (item.get("mase") or {}).get("error_kind"),
                "baseline_error_kind": _resolve_side(item, "baseline").get("error_kind"),
                "attempt_count": item.get("attempt_count"),
            }
        )
    return rows


def summarize_benchmark_file(path: str | Path) -> dict[str, Any]:
    summary = load_summary(path)
    results = summary.get("results") or []
    return {
        "source_path": str(Path(path).resolve()),
        "benchmark": summary.get("benchmark"),
        "run_id": summary.get("run_id"),
        "sample_count": len(results),
        "mase": summarize_side(results, "mase"),
        "baseline": summarize_side(results, "baseline"),
        "per_sample": build_per_sample_rows(results),
        "scoreboard": summary.get("scoreboard"),
        "memory_dir": summary.get("memory_dir"),
    }


def main() -> None:
    args = parse_args()
    aggregate = summarize_benchmark_file(args.path)
    if args.output:
        output_path = Path(args.output)
    else:
        source = Path(args.path)
        output_path = RESULTS_DIR / f"{source.stem}-summary.json"
    output_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    aggregate["output_path"] = str(output_path)
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
