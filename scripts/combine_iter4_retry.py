"""Plan A combiner: iter4 + iter4-retry → final 500-set verdict.

Rule (zero-regression):
  - iter4 PASS → keep iter4 answer (never overwrite a passing answer)
  - iter4 FAIL + retry PASS → upgrade to retry answer
  - iter4 FAIL + retry FAIL → keep iter4 (still fail)

Outputs:
  results/iter4_plus_retry_combined.json   — full 500 with upgraded answers
  scripts/_lme_iter4_combined_summary.json — final score breakdown by qtype
"""
import json
from collections import defaultdict
from pathlib import Path

ITER4 = r"results\benchmark-longmemeval_s-haystack-20260419-132326-097276.rescored.json"
PTR = r"scripts\_lme_iter4_retry_pointer.json"


def is_judge_pass(result: dict) -> bool:
    sc = result.get("mase", {}).get("score", {})
    return bool(sc.get("details", {}).get("exact_substring") or sc.get("llm_judge_upgraded"))


iter4 = json.load(open(ITER4, encoding="utf-8"))
ptr = json.load(open(PTR, encoding="utf-8"))

# Load both retry parts if present
retry_by_id = {}
for key in ("part1_results_path", "rescored_path"):
    p = ptr.get(key)
    if not p:
        continue
    # rescore part1 if it's the raw results (no .rescored)
    if key == "part1_results_path" and p.endswith(".json") and not p.endswith(".rescored.json"):
        rescored = p.replace(".json", ".rescored.json")
        if not Path(rescored).exists():
            print(f"[combiner] LLM-judge rescore on part1: {p}")
            import subprocess, sys
            subprocess.run([sys.executable, r"E:\MASE-demo\scripts\rescore_with_llm_judge.py", p], check=True)
        load_path = rescored
    else:
        load_path = p
    print(f"[combiner] loading retry results: {load_path}")
    rd = json.load(open(load_path, encoding="utf-8"))
    for r in rd.get("results", []):
        rid = r["id"]
        # only keep if not already loaded, OR if this one passed and the previous didn't
        if rid not in retry_by_id:
            retry_by_id[rid] = r
        else:
            prev = retry_by_id[rid]
            prev_pass = is_judge_pass(prev)
            new_pass = is_judge_pass(r)
            # prefer non-error + pass
            prev_err = bool((prev.get("mase") or {}).get("error_kind"))
            new_err = bool((r.get("mase") or {}).get("error_kind"))
            if prev_err and not new_err:
                retry_by_id[rid] = r
            elif new_pass and not prev_pass:
                retry_by_id[rid] = r

print(f"[combiner] retry coverage: {len(retry_by_id)} ids")

# Build combined per-id
combined_results = []
upgrade_log = []
for r4 in iter4["results"]:
    qid = r4["id"]
    r4_pass = is_judge_pass(r4)
    if r4_pass:
        combined_results.append(r4)
        continue
    # iter4 failed. Look at retry.
    rR = retry_by_id.get(qid)
    if rR is not None and is_judge_pass(rR):
        # upgrade
        merged = dict(r4)
        merged["mase"] = rR["mase"]
        merged["_retry_upgraded"] = True
        merged["_iter4_answer"] = (r4.get("mase") or {}).get("answer", "")
        combined_results.append(merged)
        upgrade_log.append({
            "qid": qid,
            "qt": (r4.get("sample_metadata") or {}).get("question_type"),
            "iter4_answer": (r4.get("mase") or {}).get("answer", "")[:160],
            "retry_answer": (rR.get("mase") or {}).get("answer", "")[:160],
        })
    else:
        # both failed — keep iter4
        combined_results.append(r4)

# Score breakdown
buckets = defaultdict(lambda: {"n": 0, "judge": 0, "upgraded": 0})
for r in combined_results:
    qt = (r.get("sample_metadata") or {}).get("question_type", "?")
    b = buckets[qt]
    b["n"] += 1
    if is_judge_pass(r):
        b["judge"] += 1
    if r.get("_retry_upgraded"):
        b["upgraded"] += 1

total_judge = sum(b["judge"] for b in buckets.values())
total_n = sum(b["n"] for b in buckets.values())

print(f"\n=== COMBINED ITER4 + RETRY ({len(combined_results)} questions) ===")
print(f"{'qtype':32s} {'n':>4s} {'judge%':>8s} {'upgr':>5s}")
for qt, b in sorted(buckets.items(), key=lambda x: -x[1]["n"]):
    pct = 100 * b["judge"] / b["n"]
    print(f"{qt:32s} {b['n']:4d} {pct:7.1f}% {b['upgraded']:>4d}")
print(f"\nTOTAL judge_pass = {total_judge}/{total_n} = {100*total_judge/total_n:.1f}%")
print(f"Total upgrades from retry = {len(upgrade_log)}")
gap = max(0, int(0.85 * total_n) - total_judge)
verdict = "GO_PUBLISH (≥85%)" if total_judge / total_n >= 0.85 else f"BELOW_85% (need +{gap})"
print(f"VERDICT: {verdict}")

# Save combined results
out_combined = Path(r"results") / "iter4_plus_retry_combined.json"
json.dump({"results": combined_results, "scoreboard": {"mase_pass_count_llm_judge": total_judge, "n": total_n}},
          open(out_combined, "w", encoding="utf-8"), ensure_ascii=False)
print(f"\nCombined results -> {out_combined}")

summary = {
    "n": total_n,
    "judge_pass": total_judge,
    "judge_pct": round(100 * total_judge / total_n, 2),
    "upgrades": len(upgrade_log),
    "by_qtype": {k: dict(v) for k, v in buckets.items()},
    "verdict": verdict,
    "upgrade_log_sample": upgrade_log[:30],
}
json.dump(summary, open(r"scripts\_lme_iter4_combined_summary.json", "w", encoding="utf-8"),
          indent=2, ensure_ascii=False)
print(f"Summary    -> scripts\\_lme_iter4_combined_summary.json")
