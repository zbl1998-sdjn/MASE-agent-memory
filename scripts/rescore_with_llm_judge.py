"""Post-hoc LLM judge rescorer for LongMemEval results.

Takes a benchmark result JSON, walks every FAILED sample, and asks the LLM
judge whether the MASE answer is semantically correct. Conservative: we only
flip 0 → 1, never the other way (the original substring score is the floor).

Usage:
    python scripts/rescore_with_llm_judge.py <result_json> [<result_json> ...]

Output:
    For each input, writes <result>_rescored.json next to it and prints a
    side-by-side summary table.

Judge model:
    Reuses benchmarks/llm_judge.py which loads ModelInterface from
    MASE_CONFIG_PATH. We force it to use deepseek-chat (cheapest cloud) by
    pointing at config.lme_glm5.json + setting the executor mode to one that
    is cheap. The judge prompt is fixed inside llm_judge.py.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(r"E:\MASE-demo")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

os.environ.setdefault("MASE_CONFIG_PATH", str(REPO / "config.lme_glm5.json"))
os.environ["MASE_USE_LLM_JUDGE"] = "1"

from benchmarks.llm_judge import judge_answer  # noqa: E402

JUDGE_MODE = "grounded_verify_lme_english"  # kimi-k2.5 + deepseek + glm fallback chain
MAX_WORKERS = 6


def _is_pass(sample: dict) -> bool:
    s = sample.get("mase", {}).get("score", {})
    if isinstance(s, dict):
        return bool(s.get("all_matched"))
    return bool(s)


def _answer_of(sample: dict) -> str:
    return str(sample.get("mase", {}).get("answer") or "").strip()


def _gt_of(sample: dict) -> str:
    return str(sample.get("ground_truth") or "").strip()


def rescore_one(sample: dict) -> tuple[str, bool, bool, str]:
    qid = str(sample.get("id") or "")
    if _is_pass(sample):
        return qid, True, True, "already_pass"
    ans = _answer_of(sample)
    gt = _gt_of(sample)
    q = str(sample.get("question") or "")
    if not ans or not gt:
        return qid, False, False, "empty"
    try:
        verdict = judge_answer(q, gt, ans, mode=JUDGE_MODE)
    except Exception as e:
        return qid, False, False, f"judge_err:{type(e).__name__}"
    if verdict is True:
        return qid, False, True, "upgraded"
    if verdict is False:
        return qid, False, False, "judge_confirmed_fail"
    return qid, False, False, "judge_unavailable"


def rescore_file(path: Path) -> dict:
    print(f"\n=== {path.name} ===")
    j = json.loads(path.read_text(encoding="utf-8"))
    samples = j.get("results", [])
    n = len(samples)
    sub_pass = sum(1 for s in samples if _is_pass(s))
    print(f"  loaded n={n}, substring_pass={sub_pass} ({round(100*sub_pass/max(1,n),2)}%)")

    upgraded_qids = []
    confirmed_qids = []
    unavail_qids = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(rescore_one, s): i for i, s in enumerate(samples)}
        done = 0
        for fut in as_completed(futs):
            qid, was_pass, now_pass, reason = fut.result()
            done += 1
            if not was_pass and now_pass:
                upgraded_qids.append(qid)
            elif not was_pass and reason == "judge_confirmed_fail":
                confirmed_qids.append(qid)
            elif not was_pass and reason == "judge_unavailable":
                unavail_qids.append(qid)
            if done % 25 == 0:
                print(f"  judge progress {done}/{n}  upgraded={len(upgraded_qids)}  elapsed={(time.time()-t0):.0f}s")

    new_pass = sub_pass + len(upgraded_qids)
    new_pct = round(100 * new_pass / max(1, n), 2)
    sub_pct = round(100 * sub_pass / max(1, n), 2)
    delta = round(new_pct - sub_pct, 2)
    print(f"  RESULT: substring={sub_pct}% → llm_judge={new_pct}%  (Δ +{delta}pp, +{len(upgraded_qids)} upgraded, {len(unavail_qids)} judge-unavailable)")

    upgraded_set = set(upgraded_qids)
    for s in samples:
        qid = str(s.get("id") or "")
        if qid in upgraded_set:
            sc = s.setdefault("mase", {}).setdefault("score", {})
            if isinstance(sc, dict):
                sc["llm_judge_upgraded"] = True
                sc["all_matched"] = True
                sc["score"] = 1.0

    j.setdefault("scoreboard", {})["mase_pass_count_llm_judge"] = new_pass
    j["scoreboard"]["mase_pass_count_substring"] = sub_pass
    j["scoreboard"]["llm_judge_upgrades"] = len(upgraded_qids)
    j["scoreboard"]["llm_judge_unavailable"] = len(unavail_qids)
    j["llm_judge_meta"] = {
        "judge_mode": JUDGE_MODE,
        "judged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "upgraded_qids": upgraded_qids,
        "judge_unavailable_qids": unavail_qids,
    }

    out = path.with_suffix(".rescored.json")
    out.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out.name}")

    return {
        "file": path.name,
        "n": n,
        "substring_pass": sub_pass,
        "substring_pct": sub_pct,
        "llm_judge_pass": new_pass,
        "llm_judge_pct": new_pct,
        "delta_pp": delta,
        "upgraded": len(upgraded_qids),
        "judge_unavailable": len(unavail_qids),
    }


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: rescore_with_llm_judge.py <result_json> [...]")
        return 1
    summaries = [rescore_file(Path(p)) for p in argv]
    print("\n=== SUMMARY ===")
    print(f"{'file':<70} {'n':>4} {'substr%':>8} {'judge%':>8} {'Δpp':>6} {'+up':>4}")
    for s in summaries:
        print(f"{s['file']:<70} {s['n']:>4} {s['substring_pct']:>8} {s['llm_judge_pct']:>8} {s['delta_pp']:>+6} {s['upgraded']:>4}")
    out_path = REPO / "scripts" / "_lme_rescored_summary.json"
    out_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsummary → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
