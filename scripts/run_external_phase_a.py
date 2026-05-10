"""Phase A external benchmark sweep — NoLiMa hard + BAMBOO anti-hallucination.

Runs sequentially through the local Ollama cluster. Outputs per-task JSON +
appended summary line so a tail of the log gives a quick pass/fail view.

NoLiMa:
  * needle_set_hard at 4k / 8k / 16k, depth=50%, 2 haystacks per length
BAMBOO (anti-hallucination subset, 16k):
  * altqa, senhallu, abshallu — full samples
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "benchmarks" / "external-benchmarks"


def _resolve_runs_dir() -> Path:
    raw = os.environ.get("MASE_RUNS_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (ROOT.parent / "MASE-runs").resolve()


RUNS_DIR = _resolve_runs_dir()
OUT = RUNS_DIR / "results" / "external"
OUT.mkdir(parents=True, exist_ok=True)

env = os.environ.copy()
env["PYTHONPATH"] = f"{ROOT};{ROOT / 'src'}"
env["PYTHONIOENCODING"] = "utf-8"
env["MASE_RUNS_DIR"] = str(RUNS_DIR)

SUMMARY = OUT / "phase_a_summary.jsonl"


def log_summary(record: dict) -> None:
    record["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with SUMMARY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[summary] {record}", flush=True)


def run_nolima(needle_set: str, length: int, haystacks: int = 2) -> None:
    label = needle_set.replace("needle_set_", "")
    run_dir = OUT / f"nolima_{label}_{length}"
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(EXT / "NoLiMa" / "run_mase_official.py"),
        "--needle-set-path", str(EXT / "NoLiMa" / "data" / "needlesets" / f"{needle_set}.json"),
        "--haystack-dir", str(EXT / "NoLiMa" / "data" / "haystack" / "rand_shuffle"),
        "--context-length", str(length),
        "--document-depth-percent-min", "50",
        "--document-depth-percent-max", "50",
        "--document-depth-percent-intervals", "1",
        "--metric", "contains",
        "--limit-haystacks", str(haystacks),
        "--executor-role", "general",
        "--run-dir", str(run_dir),
    ]
    print(f"\n=== NoLiMa {label} @ {length} tokens ===", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")
    dt = time.time() - t0

    summary_file = run_dir / "nolima.summary.json"
    accuracy = passed = processed = None
    if summary_file.exists():
        try:
            data = json.loads(summary_file.read_text(encoding="utf-8"))
            agg = data.get("summary", {})
            accuracy = agg.get("accuracy")
            passed = agg.get("passed")
            processed = agg.get("processed")
        except Exception as e:
            print(f"  parse summary fail: {e}", flush=True)
    log_summary({
        "task": f"nolima_{label}",
        "context_length": length,
        "accuracy": accuracy,
        "passed": passed,
        "processed": processed,
        "duration_s": round(dt, 1),
        "returncode": proc.returncode,
    })
    if proc.returncode != 0:
        print(proc.stderr[-2000:], flush=True)


def run_bamboo(task: str, length: str = "16k") -> None:
    dataset = EXT / "BAMBOO" / "datasets" / f"{task}_{length}.jsonl"
    if not dataset.exists():
        log_summary({"task": f"bamboo_{task}_{length}", "error": "dataset_missing"})
        return
    run_dir = OUT / f"bamboo_{task}_{length}"
    run_dir.mkdir(parents=True, exist_ok=True)
    output_jsonl = run_dir / "predictions.jsonl"
    cmd = [
        sys.executable,
        str(EXT / "BAMBOO" / "run_mase_official.py"),
        "--dataset", str(dataset),
        "--output", str(output_jsonl),
        "--run-dir", str(run_dir),
        "--executor-role", "auto",
    ]
    print(f"\n=== BAMBOO {task} @ {length} ===", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")
    dt = time.time() - t0
    log_summary({
        "task": f"bamboo_{task}_{length}",
        "duration_s": round(dt, 1),
        "returncode": proc.returncode,
        "output": str(output_jsonl),
    })
    if proc.returncode != 0:
        print(proc.stderr[-2000:], flush=True)


def main() -> None:
    print(f"[phase-a] starting at {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"[phase-a] summary file: {SUMMARY}", flush=True)

    # NoLiMa ONLYDirect — pure single-hop retrieval, the actual MASE capability test
    for length in (4096, 8192, 16384, 32768):
        run_nolima("needle_set_ONLYDirect", length, haystacks=2)

    # NoLiMa hard — small comparison to honestly document parametric-knowledge ceiling
    # (qwen2.5:7b lacks world knowledge for two-hop; expected ~10-20% per paper)
    run_nolima("needle_set_hard", 8192, haystacks=2)

    # BAMBOO: anti-hallucination triplet (the 3 tasks closest to MASE's pitch)
    for task in ("altqa", "senhallu", "abshallu"):
        run_bamboo(task, "16k")

    print(f"\n[phase-a] DONE at {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)


if __name__ == "__main__":
    main()
