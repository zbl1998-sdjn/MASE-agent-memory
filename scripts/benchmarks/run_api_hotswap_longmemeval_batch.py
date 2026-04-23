from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import PROJECT_ROOT
except ImportError:
    from _bootstrap import PROJECT_ROOT
from mase.model_interface import resolve_config_path
from run_api_hotswap_longmem_smoke import TEMP_ENV_PATH, build_runtime_config, require_env, write_env_file
from summarize_benchmark_result import summarize_benchmark_file

from benchmarks.runner import BenchmarkRunner

BASE_DIR = PROJECT_ROOT
RESULTS_DIR = BASE_DIR / "results"
WORKSPACE_DIR = BASE_DIR / "memory_runs" / "api-hotswap-longmemeval-batch"
RUNTIME_CONFIG_PATH = WORKSPACE_DIR / "config.runtime.json"
RUNTIME_ENV_PATH = WORKSPACE_DIR / ".env.runtime"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用云端热插拔配置运行 LongMemEval 批量测试")
    parser.add_argument("--sample-limit", type=int, default=500, help="测试样本数")
    parser.add_argument("--baseline-profile", type=str, default="none", help="baseline profile；默认跳过")
    parser.add_argument("--baseline-timeout", type=float, default=180, help="baseline 单次请求超时秒数")
    return parser.parse_args()


def prepare_runtime_files() -> Path:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    write_env_file(
        {
            "DEEPSEEK_API_KEY": require_env("DEEPSEEK_API_KEY"),
            "MINIMAX_API_KEY": require_env("MINIMAX_API_KEY"),
            "QWEN35_PLUS_API_KEY": require_env("QWEN35_PLUS_API_KEY"),
            "KIMI_K25_API_KEY": require_env("KIMI_K25_API_KEY"),
            "GLM51_API_KEY": require_env("GLM51_API_KEY"),
        }
    )
    if TEMP_ENV_PATH.exists():
        RUNTIME_ENV_PATH.write_text(TEMP_ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    runtime_config = build_runtime_config()
    runtime_config["env_file"] = str(RUNTIME_ENV_PATH.resolve())
    runtime_config["memory"]["json_dir"] = str((WORKSPACE_DIR / "memory").resolve())
    runtime_config["memory"]["index_db"] = str((WORKSPACE_DIR / "memory" / "index.db").resolve())
    RUNTIME_CONFIG_PATH.write_text(json.dumps(runtime_config, ensure_ascii=False, indent=2), encoding="utf-8")
    return RUNTIME_CONFIG_PATH


def _latest_case_record(case_memory_dir: str) -> dict[str, Any] | None:
    case_dir = Path(case_memory_dir)
    if not case_dir.exists():
        return None
    candidates = sorted(
        [path for path in case_dir.rglob("*.json") if "logs" not in path.parts],
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        return None
    try:
        return json.loads(candidates[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def summarize_runtime_memory(summary_path: str | Path) -> dict[str, Any]:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    results = summary.get("results") or []
    route_search_count = 0
    retrieval_hit_count = 0
    joint_success_count = 0
    memory_rows: list[dict[str, Any]] = []
    for item in results:
        mase = item.get("mase") or {}
        route_action = str(mase.get("route_action") or "")
        route_used_memory = route_action == "search_memory"
        if route_used_memory:
            route_search_count += 1
        record = _latest_case_record(str(item.get("case_memory_dir") or ""))
        metadata = (record or {}).get("metadata") or {}
        memory_result_count = int(metadata.get("memory_result_count") or 0)
        retrieval_hit = memory_result_count > 0
        if retrieval_hit:
            retrieval_hit_count += 1
        passed = bool((mase.get("score") or {}).get("all_matched"))
        if retrieval_hit and passed:
            joint_success_count += 1
        memory_rows.append(
            {
                "id": item.get("id"),
                "route_action": route_action,
                "memory_result_count": memory_result_count,
                "retrieval_hit": retrieval_hit,
                "passed": passed,
            }
        )
    sample_count = len(results)
    return {
        "sample_count": sample_count,
        "route_to_memory_count": route_search_count,
        "route_to_memory_rate": round(route_search_count / max(1, sample_count), 4),
        "retrieval_hit_count": retrieval_hit_count,
        "retrieval_hit_rate": round(retrieval_hit_count / max(1, sample_count), 4),
        "retrieval_hit_rate_on_memory_routes": round(retrieval_hit_count / max(1, route_search_count), 4),
        "joint_success_count": joint_success_count,
        "joint_success_rate": round(joint_success_count / max(1, sample_count), 4),
        "per_sample_memory": memory_rows,
    }


def main() -> None:
    args = parse_args()
    config_path = prepare_runtime_files()
    os.environ["MASE_CONFIG_PATH"] = str(config_path)
    config_path = resolve_config_path()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    runner = BenchmarkRunner(
        baseline_profile=args.baseline_profile,
        baseline_timeout_seconds=args.baseline_timeout,
    )
    summary = runner.run_benchmark(
        benchmark_name="longmemeval_s",
        sample_limit=args.sample_limit,
    )
    aggregate = summarize_benchmark_file(summary["results_path"])
    memory_aggregate = summarize_runtime_memory(summary["results_path"])
    consolidated = {
        "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "benchmark": "longmemeval_s",
        "sample_limit": args.sample_limit,
        "baseline_profile": args.baseline_profile,
        "baseline_timeout": args.baseline_timeout,
        "config_path": str(config_path),
        "env_path": str(RUNTIME_ENV_PATH),
        "benchmark_results_path": summary["results_path"],
        "aggregate": aggregate,
        "memory_aggregate": memory_aggregate,
    }
    output_path = RESULTS_DIR / f"longmemeval-cloud-batch-{consolidated['run_id']}.json"
    output_path.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2), encoding="utf-8")
    consolidated["results_path"] = str(output_path)
    print(json.dumps(consolidated, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
