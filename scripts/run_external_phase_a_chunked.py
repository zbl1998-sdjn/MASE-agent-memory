"""Drive the chunked NoLiMa runner (true MASE pipeline) at 4k/8k/16k/32k."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
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

LENGTHS = [4096, 8192, 16384, 32768]
HAYSTACKS = 2  # match baseline


def append(row: dict) -> None:
    with SUMMARY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("[chunked-summary]", row, flush=True)


def run_one(length: int) -> None:
    run_dir = OUT / f"nolima_chunked_ONLYDirect_{length}"
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(EXT / "NoLiMa" / "run_mase_chunked.py"),
        "--needle-set-path", str(EXT / "NoLiMa" / "data" / "needlesets" / "needle_set_ONLYDirect.json"),
        "--haystack-dir", str(EXT / "NoLiMa" / "data" / "haystack" / "rand_shuffle"),
        "--context-length", str(length),
        "--document-depth-percent-min", "50",
        "--document-depth-percent-max", "50",
        "--document-depth-percent-intervals", "1",
        "--metric", "contains",
        "--limit-haystacks", str(HAYSTACKS),
        "--executor-role", "general",
        "--chunk-chars", "900",
        "--chunk-overlap", "120",
        "--top-k", "8",
        "--run-dir", str(run_dir),
    ]
    print(f"\n=== NoLiMa CHUNKED ONLYDirect @ {length} ===", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")
    dt = time.time() - t0
    summary_file = run_dir / "nolima.summary.json"
    acc = passed = processed = None
    if summary_file.exists():
        try:
            data = json.loads(summary_file.read_text(encoding="utf-8"))
            agg = data.get("summary", {})
            acc = agg.get("accuracy"); passed = agg.get("passed"); processed = agg.get("processed")
        except Exception as e:
            print(f"  parse fail: {e}", flush=True)
    if proc.returncode != 0:
        print("  STDERR tail:", (proc.stderr or "")[-1500:], flush=True)
    append({
        "task": "nolima_ONLYDirect_chunked",
        "context_length": length,
        "accuracy": acc, "passed": passed, "processed": processed,
        "duration_s": round(dt, 1),
        "returncode": proc.returncode,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


def main() -> int:
    print(f"[chunked-driver] starting at {datetime.now()}", flush=True)
    for L in LENGTHS:
        run_one(L)
    print(f"[chunked-driver] DONE at {datetime.now()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
