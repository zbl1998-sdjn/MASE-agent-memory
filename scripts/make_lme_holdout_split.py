"""LongMemEval-S 500 → dev/test split for anti-overfitting iter3+ tuning.

Rules
-----
- Stratified by question type bucket (regular / gpt4_ / _abs) so dev and test
  share the same difficulty mix.
- Deterministic seed (42) so reruns are reproducible.
- dev = 250 (used for prompt tuning + iter design)
- test = 250 (frozen — touched ONCE per iter for final report)

Outputs
-------
data/longmemeval_official/lme_dev_250.json
data/longmemeval_official/lme_test_250.json
data/longmemeval_official/lme_split_manifest.json
"""
from __future__ import annotations
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"E:\MASE-demo")
SRC = ROOT / "data" / "longmemeval_official" / "longmemeval_s_500.json"
OUT_DIR = SRC.parent
SEED = 42
DEV_PER_BUCKET_RATIO = 0.5


def bucket(qid: str) -> str:
    if qid.endswith("_abs"):
        return "abstention"
    if qid.startswith("gpt4_"):
        return "gpt4_gen"
    return "regular"


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    print(f"loaded {len(data)} samples")

    by_bucket: dict[str, list] = defaultdict(list)
    for sample in data:
        qid = str(sample.get("question_id") or sample.get("id") or "")
        by_bucket[bucket(qid)].append(sample)

    print("bucket counts:")
    for b, items in by_bucket.items():
        print(f"  {b}: {len(items)}")

    rng = random.Random(SEED)
    dev: list = []
    test: list = []
    for b, items in by_bucket.items():
        shuffled = items[:]
        rng.shuffle(shuffled)
        cut = round(len(shuffled) * DEV_PER_BUCKET_RATIO)
        dev.extend(shuffled[:cut])
        test.extend(shuffled[cut:])

    rng.shuffle(dev)
    rng.shuffle(test)

    dev_path = OUT_DIR / "lme_dev_250.json"
    test_path = OUT_DIR / "lme_test_250.json"
    dev_path.write_text(json.dumps(dev, ensure_ascii=False), encoding="utf-8")
    test_path.write_text(json.dumps(test, ensure_ascii=False), encoding="utf-8")

    manifest = {
        "source": str(SRC),
        "seed": SEED,
        "split_method": "stratified by qid bucket (regular / gpt4_gen / abstention)",
        "purpose": {
            "dev": "iter3+ prompt tuning, verifier routing design — touch as much as you want",
            "test": "FROZEN held-out — touch ONCE per iter for final report number, anti-overfit",
        },
        "dev_count": len(dev),
        "test_count": len(test),
        "dev_bucket_counts": {
            b: sum(1 for s in dev if bucket(str(s.get("question_id") or s.get("id") or "")) == b)
            for b in by_bucket
        },
        "test_bucket_counts": {
            b: sum(1 for s in test if bucket(str(s.get("question_id") or s.get("id") or "")) == b)
            for b in by_bucket
        },
    }
    (OUT_DIR / "lme_split_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\ndev → {dev_path} ({len(dev)} samples)")
    print(f"test → {test_path} ({len(test)} samples)")
    print("\nbucket parity:")
    for b in by_bucket:
        print(f"  {b}: dev={manifest['dev_bucket_counts'][b]} test={manifest['test_bucket_counts'][b]}")


if __name__ == "__main__":
    main()
