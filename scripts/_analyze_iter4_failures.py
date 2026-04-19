"""Analyze ablation 80% LLM-judge results to find the path to 85%."""
import json
from pathlib import Path

f = Path(r"E:\MASE-demo\results\benchmark-longmemeval_s-haystack-20260419-110624-279924.rescored.json")
data = json.loads(f.read_text(encoding="utf-8"))
sb = data["scoreboard"]
upgraded = set(data["llm_judge_meta"]["upgraded_qids"])

results = data["results"]
print(f"Total: {len(results)}, substring={sb['mase_pass_count_substring']}, judge={sb['mase_pass_count_llm_judge']}")

def bucket_for_qid(qid: str) -> str:
    if qid.endswith("_abs"):
        return "abstention"
    if qid.startswith("gpt4_"):
        return "gpt4_gen"
    return "regular"

# Per-bucket breakdown
from collections import Counter

bucket_total = Counter()
bucket_pass_substring = Counter()
bucket_pass_judge = Counter()
fails = []

for r in results:
    qid = str(r["id"])
    b = bucket_for_qid(qid)
    bucket_total[b] += 1
    score = r["mase"].get("score", 0)
    if isinstance(score, dict):
        score_val = score.get("score", 0)
    else:
        score_val = score or 0
    is_substring_pass = bool(score_val and score_val > 0)
    is_judge_pass = is_substring_pass or qid in upgraded
    if is_substring_pass:
        bucket_pass_substring[b] += 1
    if is_judge_pass:
        bucket_pass_judge[b] += 1
    if not is_judge_pass:
        fails.append({
            "qid": qid,
            "bucket": b,
            "task_type": r.get("task_type"),
            "question": (r.get("question") or "")[:120],
            "answer": (r["mase"].get("answer") or "")[:200],
            "ground_truth": str(r.get("ground_truth"))[:200],
        })

print("\n=== Per-bucket pass rates ===")
for b in ("regular", "gpt4_gen", "abstention"):
    t = bucket_total[b]
    if t == 0: continue
    print(f"{b:12s}: substring={bucket_pass_substring[b]:3d}/{t:3d} ({100*bucket_pass_substring[b]/t:.1f}%)  "
          f"judge={bucket_pass_judge[b]:3d}/{t:3d} ({100*bucket_pass_judge[b]/t:.1f}%)")

print(f"\n=== {len(fails)} failures ===")
fail_buckets = Counter(f["bucket"] for f in fails)
fail_tasks = Counter(f["task_type"] for f in fails)
print("by bucket:", dict(fail_buckets))
print("by task_type:")
for k, v in fail_tasks.most_common():
    print(f"  {k}: {v}")

# Analyze abstention failures specifically — those are the 21/29 phrasing-mismatch
abs_fails = [f for f in fails if f["bucket"] == "abstention"]
print(f"\n=== {len(abs_fails)} abstention failures (sample 8) ===")
for f in abs_fails[:8]:
    print(f"--- {f['qid']}  task={f['task_type']}")
    print(f"  Q : {f['question']}")
    print(f"  GT: {f['ground_truth']}")
    print(f"  A : {f['answer']}")

print("\n=== regular failures (sample 5) ===")
reg_fails = [f for f in fails if f["bucket"] == "regular"]
for f in reg_fails[:5]:
    print(f"--- {f['qid']}  task={f['task_type']}")
    print(f"  Q : {f['question']}")
    print(f"  GT: {f['ground_truth']}")
    print(f"  A : {f['answer']}")

print("\n=== gpt4 failures (sample 5) ===")
g4_fails = [f for f in fails if f["bucket"] == "gpt4_gen"]
for f in g4_fails[:5]:
    print(f"--- {f['qid']}  task={f['task_type']}")
    print(f"  Q : {f['question']}")
    print(f"  GT: {f['ground_truth']}")
    print(f"  A : {f['answer']}")

# Save fails for later use
out = Path(r"E:\MASE-demo\scripts\_lme_iter4_fail_profile.json")
out.write_text(json.dumps({
    "n_total": len(results),
    "n_pass_judge": sb["mase_pass_count_llm_judge"],
    "by_bucket": {b: {"total": bucket_total[b], "judge_pass": bucket_pass_judge[b]} for b in bucket_total},
    "by_task_type": dict(fail_tasks),
    "fails": fails,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSaved to {out}")
