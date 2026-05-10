"""Phase A+ — NoLiMa hard set with deepseek-r1:7b reasoning role.

Demonstrates MASE's 'on-demand model activation': the same long-context
capability, but with a reasoning model swapped in for tasks that need
multi-hop world knowledge. Direct comparison vs general (qwen2.5:7b) row
in the main Phase A summary.

Runs sequentially after Phase A finishes (or in parallel — they share the
local Ollama cluster but deepseek-r1 isn't loaded by general role so memory
contention is minor on first sample).
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
SUMMARY = OUT / "phase_a_summary.jsonl"

env = os.environ.copy()
env["PYTHONPATH"] = f"{ROOT};{ROOT / 'src'}"
env["PYTHONIOENCODING"] = "utf-8"
env["MASE_RUNS_DIR"] = str(RUNS_DIR)


def log_summary(record: dict) -> None:
    record["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with SUMMARY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[summary] {record}", flush=True)


def run_nolima_reasoning(needle_set: str, length: int, haystacks: int = 2) -> None:
    label = needle_set.replace("needle_set_", "")
    run_dir = OUT / f"nolima_{label}_{length}_reasoning"
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
        "--executor-role", "reasoning",
        "--run-dir", str(run_dir),
    ]
    print(f"\n=== NoLiMa {label} @ {length} (reasoning=deepseek-r1:7b) ===", flush=True)
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
        "task": f"nolima_{label}_reasoning",
        "context_length": length,
        "executor_role": "reasoning",
        "accuracy": accuracy,
        "passed": passed,
        "processed": processed,
        "duration_s": round(dt, 1),
        "returncode": proc.returncode,
    })
    if proc.returncode != 0:
        print(proc.stderr[-2000:], flush=True)


def main() -> None:
    print(f"[phase-a-reasoning] starting at {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    # Hard set with reasoning model — the actual point of MASE's on-demand activation
    for length in (4096, 8192, 16384):
        run_nolima_reasoning("needle_set_hard", length, haystacks=2)
    print(f"\n[phase-a-reasoning] DONE at {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)


if __name__ == "__main__":
    main()
