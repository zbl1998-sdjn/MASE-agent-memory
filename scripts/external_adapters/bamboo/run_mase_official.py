from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from json_repair import loads as repair_json_loads
except Exception:  # pragma: no cover - optional fallback
    repair_json_loads = None

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from benchmarks.runner import _aggregate_call_log
from mase import MASESystem

SUPPORTED_TASKS = {
    "meetingqa",
    "paperqa",
    "altqa",
    "senhallu",
    "abshallu",
    "meetingpred",
    "showspred",
    "reportsumsort",
    "showssort",
}


def _resolve_runs_dir() -> Path:
    raw = os.environ.get("MASE_RUNS_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (REPO_ROOT.parent / "MASE-runs").resolve()


def resolve_execution_plan(task: str, requested_executor_role: str | None) -> dict[str, Any]:
    task_kind = "text"
    mode = "grounded_answer"
    default_role = "general"
    collaboration_mode: str | None = None

    if task in {"meetingqa", "paperqa"}:
        task_kind = "multiple_choice"
        mode = "structured_task"
        default_role = "reasoning"
    elif task in {"meetingpred", "showspred"}:
        task_kind = "speaker_name"
        mode = "grounded_answer"
        default_role = "reasoning"
        collaboration_mode = "off"
    elif task in {"senhallu", "abshallu"}:
        task_kind = "boolean"
        mode = "structured_task"
        default_role = "general"
    elif task in {"showssort", "reportsumsort"}:
        task_kind = "ordering"
        mode = "structured_task"
        default_role = "reasoning"
    elif task == "altqa":
        task_kind = "numeric"
        mode = "structured_task"
        default_role = "reasoning"

    executor_role = requested_executor_role or default_role
    return {
        "task_kind": task_kind,
        "mode": mode,
        "executor_role": executor_role,
        "collaboration_mode": collaboration_mode,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run official BAMBOO samples through MASE.")
    parser.add_argument("--dataset", required=True, help="Official BAMBOO jsonl path")
    parser.add_argument("--task", default=None, help="Optional BAMBOO task override")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit")
    parser.add_argument("--output", default=None, help="Official-eval-compatible jsonl output path")
    parser.add_argument("--run-dir", default=None, help="Optional run artifact directory")
    parser.add_argument(
        "--executor-role",
        default="auto",
        choices=["auto", "general", "reasoning"],
        help="MASE executor role",
    )
    return parser.parse_args()


def infer_task(dataset_path: Path, explicit_task: str | None) -> str:
    if explicit_task:
        task = explicit_task.strip().lower()
    else:
        stem = dataset_path.stem.lower()
        tokens = [token for token in re.split(r"[^a-z0-9]+", stem) if token]
        task = next((token for token in tokens if token in SUPPORTED_TASKS), tokens[0] if tokens else "")
    if task not in SUPPORTED_TASKS:
        raise ValueError(f"Unsupported BAMBOO task: {task}")
    return task


def load_records(dataset_path: Path, limit: int | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        if limit is not None and len(records) >= limit:
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            if repair_json_loads is None:
                raise
            parsed = repair_json_loads(stripped)
        if not isinstance(parsed, dict):
            raise TypeError(f"Expected JSON object in {dataset_path}, got {type(parsed).__name__}")
        records.append(parsed)
    return records


def _stringify_options(options: Any) -> str:
    if isinstance(options, list):
        return "\n".join(str(item).strip() for item in options if str(item).strip())
    return str(options or "").strip()


def _first_nonempty_line(text: str) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def format_fact_sheet(task: str, record: dict[str, Any]) -> str:
    if task in {"meetingqa", "paperqa", "meetingpred", "showspred", "senhallu", "abshallu", "altqa"}:
        return str(record.get("content") or "").strip()
    if task == "showssort":
        paragraphs = record.get("content") or []
        return "\n\n".join(f"[{index}] {str(paragraph).strip()}" for index, paragraph in enumerate(paragraphs))
    if task == "reportsumsort":
        summaries = record.get("summaries") or []
        events = "\n".join(f"[{index}] {str(item).strip()}" for index, item in enumerate(summaries))
        content = str(record.get("content") or "").strip()
        return f"Long text:\n{content}\n\nEvents:\n{events}".strip()
    raise ValueError(f"Unhandled task for fact sheet: {task}")


def build_question(task: str, record: dict[str, Any]) -> str:
    if task in {"meetingqa", "paperqa"}:
        options = _stringify_options(record.get("options"))
        return (
            "You are given an article in the fact sheet and a multiple-choice question.\n"
            "Choose the best answer and return only one letter: A, B, C, or D.\n"
            "Pay close attention to negation, comparison, and purpose clues in the question stem.\n"
            "Prefer the option that is most directly supported by the fact sheet.\n\n"
            f"Question: {str(record.get('question') or '').strip()}\n"
            f"Options:\n{options}\n\n"
            "Answer:"
        )
    if task == "altqa":
        return (
            "Answer the question based only on the document in the fact sheet.\n"
            "Return only the final number, without any explanation.\n\n"
            "Answer:"
        )
    if task in {"senhallu", "abshallu"}:
        return (
            "You are given a paper in the fact sheet and a hypothesis below.\n"
            'Return exactly "Yes." if the hypothesis is entailed, otherwise return exactly "No.".\n\n'
            f"Hypothesis: {str(record.get('hypothesis') or '').strip()}\n\n"
            "Answer:"
        )
    if task in {"meetingpred", "showspred"}:
        return (
            "You are given a long dialogue in the fact sheet.\n"
            "Predict the speaker mentioned at the end of the last sentence.\n"
            "Return only the speaker's name.\n\n"
            "Answer:"
        )
    if task in {"showssort", "reportsumsort"}:
        return (
            "The fact sheet contains five shuffled items labeled with identifiers like [0], [1], [2], [3], [4].\n"
            "Recover the original order and return only the identifiers separated by ' > '.\n"
            "Use discourse clues such as greetings, questions, replies, and closing remarks.\n"
            "Do not default to numeric label order.\n"
            "Do not add any extra words."
        )
    raise ValueError(f"Unhandled task for question: {task}")


def normalize_prediction(task: str, raw_answer: str) -> Any:
    cleaned = str(raw_answer or "").strip()
    if task in {"meetingqa", "paperqa"}:
        match = re.search(r"\b([A-D])\b", cleaned.upper())
        return match.group(1) if match else _first_nonempty_line(cleaned)
    if task == "altqa":
        match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
        return match.group(0) if match else _first_nonempty_line(cleaned)
    if task in {"senhallu", "abshallu"}:
        lowered = cleaned.lower()
        if lowered.startswith("yes"):
            return "Yes."
        if lowered.startswith("no"):
            return "No."
        return _first_nonempty_line(cleaned)
    if task in {"meetingpred", "showspred"}:
        return _first_nonempty_line(cleaned)
    if task in {"showssort", "reportsumsort"}:
        numbers = re.findall(r"\[(\d+)\]", cleaned)
        if not numbers:
            numbers = re.findall(r"\b\d+\b", cleaned)
        ordered: list[int] = []
        seen: set[int] = set()
        for item in numbers:
            value = int(item)
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
    return cleaned


def _restore_env_var(name: str, previous_value: str | None) -> None:
    if previous_value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous_value


def _build_sample_rows(
    task: str,
    record: dict[str, Any],
    sample_id: str,
    question: str,
    raw_answer: str,
    normalized_pred: Any,
    error: str | None,
    execution_plan: dict[str, Any],
    target: dict[str, Any] | None,
    metrics: dict[str, Any],
    case_memory_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output_row = {
        "id": sample_id,
        "task": task,
        "pred": normalized_pred,
        "answer": record.get("answer"),
        "raw_pred": raw_answer,
        "error": error,
    }
    detail_row = {
        "id": sample_id,
        "task": task,
        "dataset_answer": record.get("answer"),
        "prediction": normalized_pred,
        "raw_prediction": raw_answer,
        "question": question,
        "execution_plan": execution_plan,
        "executor_target": target,
        "metrics": metrics,
        "error": error,
        "case_memory_dir": str(case_memory_dir),
    }
    return output_row, detail_row


def build_sample_id(task: str, record: dict[str, Any], index: int) -> str:
    for key in ("id", "question_id", "custom_id", "title", "question"):
        value = str(record.get(key) or "").strip()
        if value:
            compact = re.sub(r"\s+", "_", value[:60])
            compact = re.sub(r"[^\w\-.]+", "", compact)
            if compact:
                return f"{task}-{index:03d}-{compact}"
    return f"{task}-{index:03d}"


def _sample_artifact_id(task: str, record: dict[str, Any], index: int) -> str:
    payload = json.dumps(
        {"task": task, "index": index, "record": record},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"sample-{index:03d}-{digest}"


def run_sample(
    task: str,
    record: dict[str, Any],
    index: int,
    run_dir: Path,
    executor_role: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sample_id = build_sample_id(task, record, index)
    case_memory_dir = run_dir / "case_memory" / _sample_artifact_id(task, record, index)
    case_memory_dir.mkdir(parents=True, exist_ok=True)
    previous_memory_dir = os.environ.get("MASE_MEMORY_DIR")
    previous_task_profile = os.environ.get("MASE_TASK_PROFILE")
    os.environ["MASE_MEMORY_DIR"] = str(case_memory_dir.resolve())
    os.environ["MASE_TASK_PROFILE"] = f"external_text_task_{task}"

    question = build_question(task, record)
    fact_sheet = format_fact_sheet(task, record)
    execution_plan = resolve_execution_plan(task, executor_role)
    system = MASESystem()
    system.model_interface.reset_call_log()
    started = time.perf_counter()
    raw_answer = ""
    error = None
    target: dict[str, Any] | None = None

    try:
        target = system.describe_executor_target(
            mode=str(execution_plan["mode"]),
            user_question=question,
            use_memory=True,
            executor_role=str(execution_plan["executor_role"]),
        )
        target["task_kind"] = execution_plan["task_kind"]
        target["requested_collaboration_mode"] = execution_plan["collaboration_mode"]
        raw_answer = system.call_executor(
            user_question=question,
            fact_sheet=fact_sheet,
            allow_general_knowledge=False,
            task_type=str(execution_plan["mode"]),
            use_memory=True,
            executor_role=str(execution_plan["executor_role"]),
            collaboration_mode=execution_plan["collaboration_mode"],
        )
    except Exception as exc:  # pragma: no cover - runtime safety
        error = f"{type(exc).__name__}: {exc}"
    finally:
        _restore_env_var("MASE_MEMORY_DIR", previous_memory_dir)
        _restore_env_var("MASE_TASK_PROFILE", previous_task_profile)

    metrics = _aggregate_call_log(system.model_interface.get_call_log())
    metrics["wall_clock_seconds"] = round(time.perf_counter() - started, 6)
    normalized_pred = normalize_prediction(task, raw_answer)
    return _build_sample_rows(
        task,
        record,
        sample_id,
        question,
        raw_answer,
        normalized_pred,
        error,
        execution_plan,
        target,
        metrics,
        case_memory_dir,
    )


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset).resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    executor_role = None if args.executor_role == "auto" else args.executor_role
    task = infer_task(dataset_path, args.task)
    records = load_records(dataset_path, args.limit)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_run_dir = (
        _resolve_runs_dir()
        / "external-benchmarks"
        / "BAMBOO"
        / "outputs"
        / f"mase-{task}-{dataset_path.stem}-{timestamp}"
    )
    run_dir = Path(args.run_dir).resolve() if args.run_dir else default_run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    output_path = Path(args.output).resolve() if args.output else run_dir / f"{task}.predictions.jsonl"
    details_path = run_dir / f"{task}.details.json"
    summary_path = run_dir / f"{task}.summary.json"

    outputs: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        output_row, detail_row = run_sample(
            task=task,
            record=record,
            index=index,
            run_dir=run_dir,
            executor_role=executor_role,
        )
        outputs.append(output_row)
        details.append(detail_row)
        print(
            json.dumps(
                {
                    "index": index,
                    "total": len(records),
                    "id": output_row["id"],
                    "error": output_row["error"],
                    "pred": output_row["pred"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    with output_path.open("w", encoding="utf-8") as handle:
        for row in outputs:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "task": task,
        "dataset": str(dataset_path),
        "sample_count": len(outputs),
        "output_path": str(output_path),
        "details_path": str(details_path),
        "executor_role": args.executor_role,
        "error_count": sum(1 for row in outputs if row.get("error")),
        "sort_parse_fail_count": sum(
            1
            for row in outputs
            if task in {"showssort", "reportsumsort"} and not isinstance(row.get("pred"), list)
        ),
    }

    details_path.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
