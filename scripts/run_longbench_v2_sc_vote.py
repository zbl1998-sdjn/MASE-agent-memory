"""LongBench-v2 self-consistency vote: run N benchmark passes at different temps,
then majority-vote on extracted MC letter per sample.

Usage:
    python scripts/run_longbench_v2_sc_vote.py --length short --limit 30 --gpu 0
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"


def _extract_choice(text: str) -> str | None:
    if not text:
        return None
    upper = text.upper()
    m = re.search(r"FINAL\s*ANSWER\s*[:\-]\s*\(?([A-D])\)?", upper)
    if m:
        return m.group(1)
    m = re.search(r"(?:ANSWER|答案)\s*[:：\-]\s*\(?([A-D])\)?", upper)
    if m:
        return m.group(1)
    for line in reversed([l.strip() for l in upper.splitlines() if l.strip()]):
        if len(line) <= 6:
            mm = re.search(r"\b([A-D])\b", line)
            if mm:
                return mm.group(1)
    m = re.search(r"\b([A-D])\b", upper)
    return m.group(1) if m else None


def find_latest_result(prefix: str, after_ts: float) -> Path | None:
    cands = sorted(
        (p for p in RESULTS_DIR.glob(f"{prefix}*.json") if p.stat().st_mtime >= after_ts),
        key=lambda p: p.stat().st_mtime,
    )
    return cands[-1] if cands else None


def run_pass(temp: float, length: str, limit: int, gpu: str, config: str) -> Path:
    env = dict(os.environ)
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "MASE_MULTIPASS": "1",
        "MASE_MULTIPASS_VARIANTS": "2",
        "MASE_MULTIPASS_HYDE": "1",
        "MASE_MULTIPASS_RERANK": "1",
        "MASE_TEMP_OVERRIDE": str(temp),
        "MASE_LONG_CONTEXT_VARIANT": "mc",
        "MASE_CONFIG_PATH": config,
        "CUDA_VISIBLE_DEVICES": gpu,
    })
    started = time.time()
    cmd = [
        sys.executable, "scripts/run_longbench_v2.py",
        "--length", length, "--limit", str(limit), "--gpu", gpu,
        "--config", config,
        "--out", str(ROOT / "scripts" / f"_lbv2_sc_temp{temp:.1f}.json"),
    ]
    print(f"[sc-vote] PASS temp={temp} ...", flush=True)
    proc = subprocess.run(cmd, env=env, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print("STDOUT:", proc.stdout[-2000:]); print("STDERR:", proc.stderr[-2000:])
        raise SystemExit(f"pass temp={temp} failed (rc={proc.returncode})")
    rp = find_latest_result("benchmark-longbench_v2-standard-", started)
    if not rp:
        raise SystemExit(f"no results json found after pass temp={temp}")
    print(f"[sc-vote] temp={temp} -> {rp.name}", flush=True)
    return rp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--length", default="short")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--config", default=str(ROOT / "config.dual_gpu.json"))
    parser.add_argument("--temps", default="0.0,0.6,0.9")
    args = parser.parse_args()

    temps = [float(t) for t in args.temps.split(",")]
    pass_files: list[Path] = []
    for t in temps:
        pass_files.append(run_pass(t, args.length, args.limit, args.gpu, args.config))

    # Per-sample vote
    all_passes = [json.loads(p.read_text(encoding="utf-8")) for p in pass_files]
    by_id: dict[str, list[dict]] = {}
    for pj in all_passes:
        for r in pj["results"]:
            by_id.setdefault(r["id"], []).append(r)

    voted = 0
    pass_individual = [0] * len(temps)
    for sid, rows in by_id.items():
        gt = str(rows[0]["ground_truth"]).strip().upper()
        letters = []
        for i, r in enumerate(rows):
            ans = r["mase"].get("answer") or ""
            ext = _extract_choice(ans)
            if ext:
                letters.append(ext)
            sc = r["mase"].get("score") or {}
            if isinstance(sc, dict) and sc.get("score") == 1.0:
                pass_individual[i] += 1
        if not letters:
            continue
        most = Counter(letters).most_common(1)[0][0]
        if most == gt:
            voted += 1

    n = len(by_id)
    summary = {
        "benchmark": "longbench_v2",
        "length_filter": args.length,
        "limit": args.limit,
        "temps": temps,
        "n_samples": n,
        "individual_pass": [{"temp": t, "passed": p, "pct": round(100 * p / n, 2)}
                            for t, p in zip(temps, pass_individual)],
        "vote_passed": voted,
        "vote_pass_pct": round(100 * voted / max(1, n), 2),
        "passes_files": [str(p) for p in pass_files],
    }
    out = ROOT / "scripts" / "_longbench_v2_sc_vote_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
