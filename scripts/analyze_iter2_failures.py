"""Extract iter2 LME failures by bucket + abstention correctness analysis."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"E:\MASE-demo")
SRC = ROOT / "results" / "benchmark-longmemeval_s-haystack-20260419-020951-451050.json"


def bucket(qid: str) -> str:
    if qid.endswith("_abs"):
        return "abstention"
    if qid.startswith("gpt4_"):
        return "gpt4_gen"
    return "regular"


ABSTENTION_PHRASES = [
    "did not mention",
    "not mention",
    "no information",
    "don't have",
    "do not have",
    "no record",
    "not in my",
    "no mention",
    "cannot find",
    "can't find",
    "i don't know",
    "i do not know",
    "haven't mentioned",
    "没有提到",
    "没有记录",
    "我不知道",
]


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    results = data["results"]
    fails = []
    passes = 0
    for r in results:
        s = r.get("mase", {}).get("score", {})
        if isinstance(s, dict):
            val = float(s.get("score") or 0)
        else:
            val = float(s or 0)
        if val >= 0.999:
            passes += 1
        else:
            fails.append({
                "id": r["id"],
                "bucket": bucket(r["id"]),
                "task_type": r.get("task_type", "?"),
                "question": r["question"][:300],
                "ground_truth": str(r["ground_truth"])[:300],
                "mase_answer": str(r["mase"].get("answer", ""))[:400],
                "score": val,
            })

    print(f"pass={passes}  fail={len(fails)}  (scoreboard said 305/195)")
    print("fails by bucket:", dict(Counter(f["bucket"] for f in fails)))

    abst = [f for f in fails if f["bucket"] == "abstention"]
    pseudo_correct = 0
    true_hallucinate = 0
    for f in abst:
        ans_lower = f["mase_answer"].lower()
        if any(k in ans_lower for k in ABSTENTION_PHRASES):
            pseudo_correct += 1
        else:
            true_hallucinate += 1
    print(
        f"\nabstention analysis ({len(abst)} fails):"
        f"\n  semantic-correct-but-scorer-rejected = {pseudo_correct}"
        f"\n  true-hallucinate                     = {true_hallucinate}"
    )

    gpt4 = [f for f in fails if f["bucket"] == "gpt4_gen"]
    print(f"\ngpt4_gen fail task_types: {dict(Counter(f['task_type'] for f in gpt4))}")

    reg = [f for f in fails if f["bucket"] == "regular"]
    print(f"\nregular fail task_types: {dict(Counter(f['task_type'] for f in reg))}")

    (ROOT / "scripts" / "_iter2_failures.json").write_text(
        json.dumps(fails, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nsaved scripts/_iter2_failures.json")


if __name__ == "__main__":
    main()
