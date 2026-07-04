"""XFUND-zh **train split** 中文表单诊断集构建器(与冻结评测零重叠)。

用途:治 dev 过拟合——冻结评测的 xfund_zh 仅 10 例 dev,调参面太小,易过拟合。
XFUND train(149 docs)与评测用的 zh.val 完全不同文档,取样做**诊断集**(不入
frozen manifest、不进正式成绩),仅供优化期取证与模型 A/B 的验证面。

复用 build_suite.py 的 extract_xfund_pairs(同一套标注卫生规则)与锚串归一化。

用法:
    python -X utf8 benchmarks/multimodal_eval/build_xfund_diag.py [--n 30] [--seed 20260704]
产物:benchmarks/multimodal_eval/diag_xfund_train.json(仓内,只含 GT,图在仓外)
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from build_suite import _norm_anchor, _sha256_file, extract_xfund_pairs

_HERE = Path(__file__).resolve().parent
_XFUND_ROOT = Path("E:/MASE-runs/datasets/external/xfund-zh")
_TRAIN_ANN = _XFUND_ROOT / "zh.train.json"
_TRAIN_IMG = _XFUND_ROOT / "train_images"
_MAX_FACTS_PER_DOC = 5


def build(n: int, seed: int) -> list[dict]:
    data = json.loads(_TRAIN_ANN.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    docs = list(data["documents"])
    rng.shuffle(docs)
    cases: list[dict] = []
    for doc in docs:
        if len(cases) >= n:
            break
        img = _TRAIN_IMG / doc["img"]["fname"]
        if not img.is_file():
            continue
        pairs = extract_xfund_pairs(doc)
        if not pairs:
            continue
        picked = pairs[:_MAX_FACTS_PER_DOC] if len(pairs) <= _MAX_FACTS_PER_DOC else rng.sample(pairs, _MAX_FACTS_PER_DOC)
        cases.append({
            "case_id": f"xfunddiag-{Path(doc['img']['fname']).stem}",
            "lane": "xfund_zh",
            "modality": "image",
            "difficulty": 2,
            "language": "zh",
            "file": str(img.resolve()),
            "sha256": _sha256_file(img),
            "anchors_fulltext": [_norm_anchor(a) for _, a in picked],
            "expected_facts": [
                {"key_hint": _norm_anchor(q)[:20] or "field", "value_anchors": [_norm_anchor(a)]}
                for q, a in picked
            ],
            "qa": [{"q": f"表单里「{picked[0][0]}」的内容是什么?", "answer_anchors": [_norm_anchor(picked[0][1])]}],
            "negative": False,
            "split": "diagnostic",
        })
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="XFUND-train 中文表单诊断集")
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260704)
    args = parser.parse_args()
    if not _TRAIN_ANN.is_file():
        print(f"[error] 缺 {_TRAIN_ANN};先下载 zh.train.json/zip 到 {_XFUND_ROOT}")
        return 2
    cases = build(args.n, args.seed)
    out = _HERE / "diag_xfund_train.json"
    out.write_text(
        json.dumps({"dataset": "xfund_diag_train", "split": "diagnostic",
                    "note": "XFUND zh.train,与冻结评测 zh.val 零重叠;仅诊断,不入正式成绩",
                    "seed": args.seed, "cases": cases}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    total_facts = sum(len(c["expected_facts"]) for c in cases)
    print(f"[ok] {len(cases)} docs / {total_facts} facts → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
