from __future__ import annotations

import json
import sys
import time
from copy import copy
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import PROJECT_ROOT
except ImportError:
    from _bootstrap import PROJECT_ROOT

REPO_ROOT = PROJECT_ROOT
NOLIMA_DIR = REPO_ROOT / "external-benchmarks" / "NoLiMa"
EVAL_DIR = NOLIMA_DIR / "evaluation"
if str(NOLIMA_DIR) not in sys.path:
    sys.path.insert(0, str(NOLIMA_DIR))
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from async_evaluate import NoLiMa_Tester

MODEL_NAME = "mase_default"
MODEL_CONFIGS_DIR = EVAL_DIR / "model_configs"
NEEDLESETS_DIR = NOLIMA_DIR / "data" / "needlesets"
HAYSTACK_DIR = NOLIMA_DIR / "data" / "haystack" / "rand_shuffle"
OUTPUT_ROOT = NOLIMA_DIR / "outputs" / "mase"
SUMMARY_ROOT = REPO_ROOT / "results" / "nolima"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_tests(
    needle_set_path: Path,
    allowed_question_types: set[str],
    max_cases: int,
    first_test_only: bool = True,
) -> list[dict[str, Any]]:
    needle_set = _load_json(needle_set_path)
    tests: list[dict[str, Any]] = []
    for exp_config in needle_set:
        system_prompt = exp_config.get("system_prompt", "")
        exp_id = exp_config["id"]
        for question_type, question in exp_config["questions"].items():
            if allowed_question_types and question_type not in allowed_question_types:
                continue
            for test_id, test in exp_config["tests"].items():
                full_needle = "" + exp_config["needle"]
                input_args = test["input_args"]
                full_question = copy(question)
                full_distractor = None
                for arg_no, arg in enumerate(input_args):
                    arg_placeholder = "{" + str(arg_no + 1) + "}"
                    if arg_placeholder in full_question:
                        full_question = full_question.replace(arg_placeholder, arg)
                    if arg_placeholder in full_needle:
                        full_needle = full_needle.replace(arg_placeholder, arg)
                    if "distractors" in exp_config and arg_placeholder in exp_config["distractors"].get(question_type, ""):
                        full_distractor = exp_config["distractors"][question_type].replace(arg_placeholder, arg)
                tests.append(
                    {
                        "exp_id": exp_id,
                        "test_id": test_id,
                        "question_type": question_type,
                        "test_name": f"{exp_id}_{test_id}_{question_type}",
                        "system_prompt": system_prompt,
                        "task_template": exp_config.get("task_template", ""),
                        "gold_answers": test.get("gold_answers", ""),
                        "seed": 42 + int(exp_id[:4]),
                        "character_set": exp_config.get("character_set", ""),
                        "needle": full_needle,
                        "retrieval_question": full_question,
                        "distractor": full_distractor,
                    }
                )
                if len(tests) >= max_cases:
                    return tests
                if first_test_only:
                    break
    return tests


def _run_suite(
    suite_name: str,
    needle_set_path: Path,
    question_types: set[str],
    context_length: int,
    haystack_files: list[str],
    max_cases: int,
    depth_percent: float = 50.0,
) -> dict[str, Any]:
    tests = _build_tests(
        needle_set_path=needle_set_path,
        allowed_question_types=question_types,
        max_cases=max_cases,
        first_test_only=True,
    )
    suite_root = OUTPUT_ROOT / suite_name
    suite_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for haystack_file in haystack_files:
        haystack_path = HAYSTACK_DIR / haystack_file
        for index, test in enumerate(tests, start=1):
            results_dir = suite_root / "raw" / f"{test['test_name']}_{haystack_path.stem}_cl{context_length}"
            results_dir.mkdir(parents=True, exist_ok=True)
            tester = NoLiMa_Tester(
                model_name=MODEL_NAME,
                model_configs_dir=str(MODEL_CONFIGS_DIR),
                needle=test["needle"],
                haystack_path=str(haystack_path),
                results_dir=str(results_dir),
                retrieval_question=test["retrieval_question"],
                gold_answers=json.dumps(test["gold_answers"]) if test["gold_answers"] != "" else "",
                character_set=json.dumps(test["character_set"]) if test["character_set"] != "" else "",
                system_prompt=test["system_prompt"],
                use_default_system_prompt=False,
                task_template=test["task_template"],
                context_length=context_length,
                document_depth_percent_min=depth_percent,
                document_depth_percent_max=depth_percent,
                document_depth_percent_intervals=1,
                static_depth=-1,
                metric="contains",
                test_name=test["test_name"],
                seed=test["seed"],
                prevent_duplicate=False,
                distractor=test["distractor"],
            )
            tester.evaluate()

            result_files = sorted(results_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
            if not result_files:
                row = {
                    "suite": suite_name,
                    "haystack_file": haystack_file,
                    "test_name": test["test_name"],
                    "question_type": test["question_type"],
                    "status": "missing_result",
                    "metric": 0,
                }
            else:
                payload = _load_json(result_files[-1])
                result_row = (payload.get("results") or [{}])[0]
                row = {
                    "suite": suite_name,
                    "haystack_file": haystack_file,
                    "test_name": test["test_name"],
                    "question_type": test["question_type"],
                    "status": "ok" if not result_row.get("error") else "adapter_error",
                    "metric": int(result_row.get("metric") or 0),
                    "response": result_row.get("response", ""),
                    "selected_character": result_row.get("selected_character"),
                    "error": result_row.get("error"),
                    "route_action": result_row.get("route_action"),
                    "case_memory_dir": result_row.get("case_memory_dir"),
                    "result_file": str(result_files[-1]),
                    "question": test["retrieval_question"],
                    "needle": test["needle"],
                }
            rows.append(row)
            print(
                f"[{suite_name}] {index}/{len(tests)} haystack={haystack_file} test={test['test_name']} "
                f"status={row['status']} metric={row['metric']}",
                flush=True,
            )

    accuracy = round(sum(int(row["metric"]) for row in rows) / max(1, len(rows)), 4)
    adapter_error_count = sum(1 for row in rows if row["status"] == "adapter_error")
    summary = {
        "suite_name": suite_name,
        "needle_set_path": str(needle_set_path),
        "question_types": sorted(question_types),
        "context_length": context_length,
        "depth_percent": depth_percent,
        "haystack_files": haystack_files,
        "model_name": MODEL_NAME,
        "sample_count": len(rows),
        "adapter_error_count": adapter_error_count,
        "accuracy": accuracy,
        "pass_count": sum(int(row["metric"]) for row in rows),
        "rows": rows,
    }
    (suite_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _write_conclusion(smoke: dict[str, Any], extended: dict[str, Any] | None, started_at: float) -> Path:
    SUMMARY_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "smoke": smoke,
        "extended": extended,
    }
    summary_path = SUMMARY_ROOT / "mase-nolima-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "MASE NoLiMa 官方泛化验证结论",
        f"- smoke: {smoke['accuracy']:.2%} ({smoke['pass_count']}/{smoke['sample_count']})",
        f"- smoke 数据: {Path(smoke['needle_set_path']).name} + {', '.join(smoke['haystack_files'])}, CL={smoke['context_length']}, depth%={smoke['depth_percent']}",
    ]
    if extended is None:
        lines.append("- extended: skipped")
    else:
        lines.append(f"- extended: {extended['accuracy']:.2%} ({extended['pass_count']}/{extended['sample_count']})")
        lines.append(
            f"- extended 数据: {Path(extended['needle_set_path']).name} + {', '.join(extended['haystack_files'])}, "
            f"CL={extended['context_length']}, depth%={extended['depth_percent']}"
        )
    if smoke["adapter_error_count"] == 0 and (extended is None or extended["adapter_error_count"] == 0):
        lines.append("- 结论: 适配已跑通；若分数低，主要反映 MASE 在 NoLiMa latent association retrieval 上的真实能力不足。")
    else:
        lines.append("- 结论: 仍存在适配层错误，需要先排除 adapter 问题。")

    conclusion_path = SUMMARY_ROOT / "mase-nolima-conclusion.txt"
    conclusion_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def main() -> None:
    started_at = time.perf_counter()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    SUMMARY_ROOT.mkdir(parents=True, exist_ok=True)

    smoke = _run_suite(
        suite_name="smoke_direct_1k",
        needle_set_path=NEEDLESETS_DIR / "needle_set_ONLYDirect.json",
        question_types={"direct"},
        context_length=1000,
        haystack_files=["rand_book_1.txt"],
        max_cases=8,
    )

    extended = None
    if smoke["adapter_error_count"] == 0:
        extended = _run_suite(
            suite_name="extended_onehop_2k",
            needle_set_path=NEEDLESETS_DIR / "needle_set.json",
            question_types={"onehop"},
            context_length=2000,
            haystack_files=["rand_book_1.txt"],
            max_cases=8,
        )

    summary_path = _write_conclusion(smoke=smoke, extended=extended, started_at=started_at)
    print(f"Summary saved to {summary_path}")


if __name__ == "__main__":
    main()
