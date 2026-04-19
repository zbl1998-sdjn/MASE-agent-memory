from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import PROJECT_ROOT
except ImportError:
    from _bootstrap import PROJECT_ROOT

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = PROJECT_ROOT
DEFAULT_MANIFEST = SCRIPT_DIR / "generalization_regression_suite.json"
OUTPUT_ROOT = PROJECT_ROOT / "results" / "generalization-regression"
COMPARISON_PATH = OUTPUT_ROOT / "comparison.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fixed LongMemEval + BAMBOO + NoLiMa generalization smoke suite.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Regression suite manifest JSON path")
    parser.add_argument("--suite", action="append", default=[], help="Run only selected suite name(s)")
    parser.add_argument(
        "--official-max-only",
        action="store_true",
        help="Prefer official-max suites for BAMBOO and NoLiMa while keeping LongMemEval coverage.",
    )
    parser.add_argument("--list", action="store_true", help="List available suite names and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    return parser.parse_args()


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _select_active_suites(
    suites: list[dict[str, Any]],
    selected: set[str],
    *,
    official_max_only: bool = False,
) -> list[dict[str, Any]]:
    active = [suite for suite in suites if not selected or suite["name"] in selected]
    if not official_max_only:
        return active
    return [
        suite
        for suite in active
        if str(suite.get("kind") or "") == "longmemeval" or str(suite.get("name") or "").endswith("-official-max")
    ]


def _run_command(command: str) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _extract_trailing_json_object(text: str) -> dict[str, Any] | None:
    source = str(text or "").strip()
    if not source:
        return None
    for index in range(len(source) - 1, -1, -1):
        if source[index] != "{":
            continue
        candidate = source[index:].strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _parse_suite_metrics(name: str, command_runs: list[dict[str, Any]]) -> dict[str, Any]:
    if name == "longmemeval-official-smoke":
        last_stdout = str((command_runs[-1] if command_runs else {}).get("stdout") or "")
        payload = _extract_trailing_json_object(last_stdout)
        if payload is None:
            payload = {}
        pass_match = re.search(r"done\s+samples=(\d+).*?\bmase_pass=(\d+)\b", last_stdout, re.IGNORECASE | re.DOTALL)
        sample_count = payload.get("sample_count")
        mase_score = payload.get("mase_score")
        if pass_match:
            sample_count = int(pass_match.group(1))
            mase_pass = int(pass_match.group(2))
            mase_score = round(mase_pass / max(1, sample_count), 4)
        return {
            "mase_score": mase_score,
            "baseline_score": payload.get("baseline_score"),
            "sample_count": sample_count,
            "benchmark": payload.get("benchmark") or "longmemeval_s",
        }

    if name == "nolima-official-smoke":
        summary_path = PROJECT_ROOT / "results" / "nolima" / "mase-nolima-summary.json"
        if not summary_path.exists():
            return {"summary_path": str(summary_path), "status": "missing"}
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        smoke = payload.get("smoke") or {}
        extended = payload.get("extended") or {}
        return {
            "summary_path": str(summary_path),
            "smoke_accuracy": smoke.get("accuracy"),
            "smoke_sample_count": smoke.get("sample_count"),
            "smoke_adapter_error_count": smoke.get("adapter_error_count"),
            "extended_accuracy": extended.get("accuracy"),
            "extended_sample_count": extended.get("sample_count"),
            "extended_adapter_error_count": extended.get("adapter_error_count"),
        }

    if name == "nolima-official-max":
        last_command = str((command_runs[-1] if command_runs else {}).get("command") or "")
        run_dir_match = re.search(r"--run-dir\s+([^\s]+)", last_command)
        if not run_dir_match:
            return {"status": "missing_run_dir"}
        run_dir = Path(run_dir_match.group(1))
        if not run_dir.is_absolute():
            run_dir = (PROJECT_ROOT / run_dir).resolve()
        summary_path = run_dir / "nolima.summary.json"
        if not summary_path.exists():
            return {"summary_path": str(summary_path), "status": "missing"}
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        summary = payload.get("summary") or {}
        return {
            "summary_path": str(summary_path),
            "sample_count": summary.get("processed"),
            "processed": summary.get("processed"),
            "passed": summary.get("passed"),
            "failed": summary.get("failed"),
            "accuracy": summary.get("accuracy"),
            "test_count": payload.get("test_count"),
            "haystack_count": payload.get("haystack_count"),
        }

    metrics: dict[str, Any] = {}
    for run in command_runs:
        stdout = str(run.get("stdout") or "")
        task_match = re.search(r"--task\s+([a-z0-9_]+)", str(run.get("command") or ""), re.IGNORECASE)
        if not task_match:
            continue
        task_name = task_match.group(1)
        score_match = re.search(r"(accuracy|Cornordinary_index|precision/recall/f1):\s*([^\r\n]+)", stdout, re.IGNORECASE)
        if score_match:
            metrics[task_name] = {
                "metric_name": score_match.group(1),
                "metric_value": score_match.group(2).strip(),
            }
    return metrics


def _metric_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _load_previous_reference() -> dict[str, Any]:
    if not COMPARISON_PATH.exists():
        return {}
    try:
        payload = json.loads(COMPARISON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    previous_reference = payload.get("previous_reference")
    return dict(previous_reference) if isinstance(previous_reference, dict) else {}


def _build_current_regression(summary: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for suite in summary.get("suites") or []:
        name = str(suite.get("name") or "").strip()
        if not name:
            continue
        result[name] = suite.get("metrics") or {}
    return result


def _pick_suite_metrics(current_regression: dict[str, Any], prefix: str) -> tuple[str, dict[str, Any]]:
    preferred_names = (f"{prefix}-official-max", f"{prefix}-official-smoke")
    for suite_name in preferred_names:
        metrics = current_regression.get(suite_name)
        if isinstance(metrics, dict) and metrics:
            return suite_name, metrics
    for suite_name, metrics in current_regression.items():
        if suite_name.startswith(f"{prefix}-official-") and isinstance(metrics, dict) and metrics:
            return suite_name, metrics
    return "", {}


def _build_comparison(summary: dict[str, Any]) -> dict[str, Any]:
    current_regression = _build_current_regression(summary)
    previous_reference = _load_previous_reference()
    current_bamboo_name, current_bamboo = _pick_suite_metrics(current_regression, "bamboo")
    current_nolima_name, current_nolima = _pick_suite_metrics(current_regression, "nolima")

    bamboo_delta: dict[str, Any] = {}
    previous_bamboo_runs = (
        previous_reference.get("bamboo_max")
        or previous_reference.get("bamboo_smoke")
        or previous_reference.get("bamboo_expanded")
        or []
    )
    for item in previous_bamboo_runs:
        task = str(item.get("task") or "").strip()
        if not task:
            continue
        previous_smoke = _metric_to_float(item.get("score"))
        current_smoke = _metric_to_float((current_bamboo.get(task) or {}).get("metric_value"))
        if previous_smoke is None or current_smoke is None:
            continue
        bamboo_delta[task] = {
            "previous_smoke": previous_smoke,
            "current_smoke": current_smoke,
            "delta": round(current_smoke - previous_smoke, 4),
            }

    nolima_previous = previous_reference.get("nolima_max_summary") or previous_reference.get("nolima_previous_summary") or {}
    if "accuracy" in current_nolima:
        current_accuracy = _metric_to_float(current_nolima.get("accuracy"))
        previous_accuracy = _metric_to_float(nolima_previous.get("smoke_accuracy"))
        nolima_delta = {
            "official_max_accuracy": current_accuracy,
            "sample_count": current_nolima.get("sample_count"),
            "processed": current_nolima.get("processed"),
            "passed": current_nolima.get("passed"),
            "failed": current_nolima.get("failed"),
        }
        if current_accuracy is not None and previous_accuracy is not None:
            nolima_delta["accuracy_delta_vs_previous_smoke"] = round(current_accuracy - previous_accuracy, 4)
    else:
        nolima_delta = {
            "smoke_accuracy_delta": round(
                (_metric_to_float(current_nolima.get("smoke_accuracy")) or 0.0)
                - (_metric_to_float(nolima_previous.get("smoke_accuracy")) or 0.0),
                4,
            ),
            "extended_accuracy_delta": round(
                (_metric_to_float(current_nolima.get("extended_accuracy")) or 0.0)
                - (_metric_to_float(nolima_previous.get("extended_accuracy")) or 0.0),
                4,
            ),
        }

    available_envs = {
        "DEEPSEEK_API_KEY": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "MINIMAX_API_KEY": bool(os.environ.get("MINIMAX_API_KEY")),
        "QWEN35_PLUS_API_KEY": bool(os.environ.get("QWEN35_PLUS_API_KEY")),
        "KIMI_K25_API_KEY": bool(os.environ.get("KIMI_K25_API_KEY")),
        "GLM51_API_KEY": bool(os.environ.get("GLM51_API_KEY")),
    }
    minimal_cloud_script = PROJECT_ROOT / "scripts" / "benchmarks" / "run_api_hotswap_generalization_smoke.py"
    if available_envs["DEEPSEEK_API_KEY"] and available_envs["MINIMAX_API_KEY"]:
        cloud_status = "minimal_external_smoke_available" if minimal_cloud_script.exists() else "partial_envs_available"
        cloud_reason = (
            "DeepSeek/Minimax-only minimal external smoke script is available."
            if minimal_cloud_script.exists()
            else "DeepSeek/Minimax keys are present, but the minimal external smoke script has not been prepared."
        )
    else:
        cloud_status = "blocked_on_env"
        cloud_reason = "DeepSeek and MiniMax API keys are both required for the minimal cloud smoke path."

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "current_regression": current_regression,
        "previous_reference": previous_reference,
        "selected_suites": {
            "bamboo": current_bamboo_name,
            "nolima": current_nolima_name,
        },
        "delta_vs_previous_smoke": {
            "bamboo": bamboo_delta,
            "nolima": nolima_delta,
        },
        "cloud_ab_feasibility": {
            "available_envs": available_envs,
            "status": cloud_status,
            "reason": cloud_reason,
        },
    }


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = _load_manifest(manifest_path)
    suites = manifest.get("suites") or []
    if args.list:
        for suite in suites:
            print(suite["name"])
        return

    selected = set(args.suite or [])
    active_suites = _select_active_suites(suites, selected, official_max_only=bool(args.official_max_only))
    if not active_suites:
        raise ValueError("No suites selected.")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    overall_summary: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "manifest_path": str(manifest_path),
        "dry_run": bool(args.dry_run),
        "suites": [],
    }

    for suite in active_suites:
        suite_name = str(suite["name"])
        print(f"[suite] {suite_name}")
        if args.dry_run:
            for command in suite.get("commands") or []:
                print(f"  {command}")
            overall_summary["suites"].append(
                {
                    "name": suite_name,
                    "kind": suite.get("kind"),
                    "dry_run": True,
                    "commands": list(suite.get("commands") or []),
                }
            )
            continue

        command_runs: list[dict[str, Any]] = []
        suite_failed = False
        for index, command in enumerate(suite.get("commands") or [], start=1):
            print(f"  [{index}/{len(suite['commands'])}] {command}")
            run_result = _run_command(str(command))
            command_runs.append(run_result)
            if run_result["returncode"] != 0:
                suite_failed = True
                print(run_result["stderr"] or run_result["stdout"])
                break

        metrics = _parse_suite_metrics(suite_name, command_runs)
        suite_output_dir = OUTPUT_ROOT / suite_name
        suite_output_dir.mkdir(parents=True, exist_ok=True)
        (suite_output_dir / "commands.json").write_text(json.dumps(command_runs, ensure_ascii=False, indent=2), encoding="utf-8")
        (suite_output_dir / "summary.json").write_text(
            json.dumps(
                {
                    "name": suite_name,
                    "kind": suite.get("kind"),
                    "failed": suite_failed,
                    "metrics": metrics,
                    "official_data": suite.get("official_data") or [],
                    "scoring": suite.get("scoring") or "",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        overall_summary["suites"].append(
            {
                "name": suite_name,
                "kind": suite.get("kind"),
                "failed": suite_failed,
                "metrics": metrics,
                "output_dir": str(suite_output_dir),
            }
        )

    summary_path = OUTPUT_ROOT / "summary.json"
    summary_path.write_text(json.dumps(overall_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison = _build_comparison(overall_summary)
    COMPARISON_PATH.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved summary to {summary_path}")


if __name__ == "__main__":
    main()
