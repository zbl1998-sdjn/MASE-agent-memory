"""Canary benchmark — tiny LV-Eval 16k slice meant for CI / smoke gating.

The full LV-Eval matrix takes hours.  This runs ~10 questions per language
on ``factrecall_zh_16k`` / ``factrecall_en_16k`` so a regression that drops
factrecall accuracy below the alert threshold gets caught in minutes.

Output is one JSON dict to stdout.  Exit code is non-zero if any of the
configured thresholds fail, suitable for CI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from mase import MASESystem  # noqa: E402

DEFAULT_THRESHOLDS = {
    "factrecall_zh_16k": 0.90,
    "factrecall_en_16k": 0.90,
}


def _run_dataset(system: MASESystem, dataset: str, samples: list[dict]) -> dict:
    correct = 0
    details = []
    for s in samples:
        question = s["question"]
        gold = s["gold"]
        os.environ["MASE_TASK_TYPE"] = "long_context_qa"
        os.environ["MASE_LVEVAL_DATASET"] = dataset.split("_")[0]
        try:
            ans = system.ask(question, log=False)
        except Exception as exc:  # noqa: BLE001
            details.append({"q": question, "ok": False, "err": repr(exc)[:200]})
            continue
        ok = gold.strip().lower() in ans.strip().lower()
        if ok:
            correct += 1
        details.append({"q": question, "gold": gold, "answer": ans[:120], "ok": ok})
    return {"dataset": dataset, "n": len(samples), "correct": correct, "accuracy": correct / max(1, len(samples)), "details": details}


def main() -> int:
    parser = argparse.ArgumentParser(description="Canary LV-Eval 16k slice")
    parser.add_argument("--samples", type=int, default=10, help="Samples per dataset (default 10)")
    parser.add_argument("--zh-threshold", type=float, default=DEFAULT_THRESHOLDS["factrecall_zh_16k"])
    parser.add_argument("--en-threshold", type=float, default=DEFAULT_THRESHOLDS["factrecall_en_16k"])
    parser.add_argument("--zh-fixture", default=os.path.join(HERE, "..", "benchmarks", "fixtures", "canary_zh.json"))
    parser.add_argument("--en-fixture", default=os.path.join(HERE, "..", "benchmarks", "fixtures", "canary_en.json"))
    args = parser.parse_args()

    system = MASESystem()
    out = {"started_at": time.time(), "results": []}
    failed = False
    for dataset, fixture, threshold in [
        ("factrecall_zh_16k", args.zh_fixture, args.zh_threshold),
        ("factrecall_en_16k", args.en_fixture, args.en_threshold),
    ]:
        try:
            samples = json.load(open(fixture, encoding="utf-8"))[: args.samples]
        except FileNotFoundError:
            out["results"].append({"dataset": dataset, "error": f"fixture missing: {fixture}"})
            failed = True
            continue
        result = _run_dataset(system, dataset, samples)
        result["threshold"] = threshold
        result["passed"] = result["accuracy"] >= threshold
        if not result["passed"]:
            failed = True
        out["results"].append(result)
    out["elapsed_s"] = round(time.time() - out["started_at"], 1)
    out["passed"] = not failed
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
