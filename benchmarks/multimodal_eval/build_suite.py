"""multimodal_eval_v1 统一套件构建器:外部公开集采样 + 合成集合并 + manifest 冻结。

用法(先跑 generate_dataset.py 产合成 lane,再跑本脚本):
    python -X utf8 benchmarks/multimodal_eval/build_suite.py \
        [--external-root E:/MASE-runs/datasets/external] [--out E:/MASE-runs/datasets/multimodal_eval_v1]

四个 lane:
- synthetic     72 例(cases_synthetic.json;端到端/溯源/负例/干扰,唯一带记忆语义)
- sroie         100 例采样(真实扫描小票,4 字段 KIE ground truth;MIT)
- xfund_zh      50 例全量(真实中文表单,question→answer KV;CC BY-NC-SA 4.0,仅内部评测)
- librispeech   50 utt 采样(真实英文朗读,逐字转写;CC BY 4.0)

统一 case 形状(runner 只认这一种):
    {case_id, lane, modality, difficulty, language, file(相对 files_root 或绝对),
     sha256, anchors_fulltext[], expected_facts[{key_hint, value_anchors[]}],
     qa[], negative, split(dev|holdout), transcript?(音频参考转写)}

反过拟合:采样一律 random.Random(SEED) 确定性;split 按案例序号 %5==0 → dev;
manifest 记全集 sample_ids_sha256 + 每文件 sha256,holdout 结果只认单次全量跑。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_HERE = _REPO / "benchmarks" / "multimodal_eval"
DATASET_NAME = "multimodal_eval_v1"
SEED = 20260703

SROIE_SAMPLE = 100
LIBRISPEECH_SAMPLE = 50
XFUND_MAX_FACTS_PER_DOC = 5


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _norm_anchor(text: str) -> str:
    """锚串预归一化:去逗号/空白,便于 runner 的归一化子串匹配。"""
    return "".join(ch for ch in text if ch not in ",， \t\n\r")


# ---------------------------------------------------------------------------
# SROIE:真实扫描小票,data/key/NNN.json = {company,date,address,total}
# ---------------------------------------------------------------------------

def build_sroie(root: Path, rng: random.Random) -> list[dict[str, Any]]:
    key_dir = root / "sroie" / "data" / "key"
    img_dir = root / "sroie" / "data" / "img"
    if not key_dir.is_dir():
        print(f"[skip] sroie 数据缺失: {key_dir}")
        return []
    stems = sorted(p.stem for p in key_dir.glob("*.json"))
    picked = rng.sample(stems, min(SROIE_SAMPLE, len(stems)))
    cases: list[dict[str, Any]] = []
    for stem in sorted(picked):
        key = json.loads((key_dir / f"{stem}.json").read_text(encoding="utf-8"))
        img = img_dir / f"{stem}.jpg"
        if not img.is_file():
            continue
        total = _norm_anchor(str(key.get("total") or ""))
        date = str(key.get("date") or "").strip()
        company = str(key.get("company") or "").strip()
        address = str(key.get("address") or "").strip()
        expected_facts = []
        anchors = []
        if total:
            expected_facts.append({"key_hint": "total", "value_anchors": [total]})
            anchors.append(total)
        if date:
            expected_facts.append({"key_hint": "date", "value_anchors": [date]})
            anchors.append(date)
        if company:
            # 公司名 OCR 变体多,fulltext 锚取首个较长词,fact 判定用整名(runner 归一化子串)
            first_token = max(company.split(), key=len)
            anchors.append(first_token)
            expected_facts.append({"key_hint": "company", "value_anchors": [first_token]})
        if address:
            expected_facts.append({"key_hint": "address", "value_anchors": [_norm_anchor(address)[:16]]})
        cases.append({
            "case_id": f"sroie-{stem}",
            "lane": "sroie",
            "modality": "image",
            "difficulty": 2,          # 真实扫描噪声,统一记 L2
            "language": "en",
            "file": str(img.resolve()),
            "sha256": _sha256_file(img),
            "anchors_fulltext": anchors,
            "expected_facts": expected_facts,
            "qa": [{"q": f"What is the total amount on receipt {stem}?", "answer_anchors": [total]}] if total else [],
            "negative": False,
        })
    return cases


# ---------------------------------------------------------------------------
# XFUND-zh:真实中文表单,question→answer linking 展开为 KV 事实
# ---------------------------------------------------------------------------

def build_xfund_zh(root: Path, rng: random.Random) -> list[dict[str, Any]]:
    ann_path = root / "xfund-zh" / "zh.val.json"
    img_dir = root / "xfund-zh" / "images"
    if not ann_path.is_file():
        print(f"[skip] xfund-zh 数据缺失: {ann_path}")
        return []
    data = json.loads(ann_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for doc in data["documents"]:
        img = img_dir / doc["img"]["fname"]
        if not img.is_file():
            continue
        by_id = {e["id"]: e for e in doc["document"]}
        pairs: list[tuple[str, str]] = []
        for entity in doc["document"]:
            if entity["label"] != "question":
                continue
            for link in entity.get("linking", []):
                other = by_id.get(link[1] if link[0] == entity["id"] else link[0])
                if other is None or other["label"] != "answer":
                    continue
                q_text = str(entity["text"]).strip()
                a_text = str(other["text"]).strip()
                # 过滤太短/太长/纯符号的 answer,保证锚串可判
                if 2 <= len(a_text) <= 30 and any(ch.isalnum() for ch in a_text):
                    pairs.append((q_text, a_text))
        if not pairs:
            continue
        picked = pairs[:XFUND_MAX_FACTS_PER_DOC] if len(pairs) <= XFUND_MAX_FACTS_PER_DOC \
            else rng.sample(pairs, XFUND_MAX_FACTS_PER_DOC)
        cases.append({
            "case_id": f"xfund-{Path(doc['img']['fname']).stem}",
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
        })
    return cases


# ---------------------------------------------------------------------------
# LibriSpeech test-clean:真实英文朗读 + 逐字参考转写
# ---------------------------------------------------------------------------

def build_librispeech(root: Path, rng: random.Random) -> list[dict[str, Any]]:
    ls_root = root / "librispeech" / "LibriSpeech" / "test-clean"
    if not ls_root.is_dir():
        print(f"[skip] librispeech 数据缺失: {ls_root}(需先解压 test-clean.tar.gz)")
        return []
    utterances: list[tuple[Path, str]] = []
    for trans in sorted(ls_root.rglob("*.trans.txt")):
        for line in trans.read_text(encoding="utf-8").splitlines():
            utt_id, _, text = line.partition(" ")
            flac = trans.parent / f"{utt_id}.flac"
            words = text.split()
            # 选择 8-30 词的句子:太短没信息量,太长评测耗时
            if flac.is_file() and 8 <= len(words) <= 30:
                utterances.append((flac, text.strip()))
    picked = rng.sample(utterances, min(LIBRISPEECH_SAMPLE, len(utterances)))
    cases: list[dict[str, Any]] = []
    for flac, text in sorted(picked, key=lambda pair: pair[0].name):
        words = [w for w in text.split() if len(w) >= 6]
        anchor_words = rng.sample(words, min(2, len(words))) if words else text.split()[:2]
        cases.append({
            "case_id": f"libri-{flac.stem}",
            "lane": "librispeech",
            "modality": "audio",
            "difficulty": 1,
            "language": "en",
            "file": str(flac.resolve()),
            "sha256": _sha256_file(flac),
            "transcript": text,          # 参考转写:runner 计 char_similarity
            "anchors_fulltext": anchor_words,
            "expected_facts": [],        # 朗读语料无业务事实,只评转写与召回
            "qa": [],
            "negative": False,
        })
    return cases


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-root", default="E:/MASE-runs/datasets/external")
    parser.add_argument("--out", default=str(Path("E:/MASE-runs/datasets") / DATASET_NAME))
    args = parser.parse_args()
    external_root = Path(args.external_root).resolve()

    synthetic_path = _HERE / "cases_synthetic.json"
    if not synthetic_path.is_file():
        print("[error] 先运行 generate_dataset.py 生成合成 lane(cases_synthetic.json)")
        return 2
    synthetic = json.loads(synthetic_path.read_text(encoding="utf-8"))

    rng = random.Random(SEED)
    external = build_sroie(external_root, rng) + build_xfund_zh(external_root, rng) \
        + build_librispeech(external_root, rng)

    cases = synthetic + external
    for index, case in enumerate(cases):
        case["split"] = "dev" if index % 5 == 0 else "holdout"

    (_HERE / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    ids = sorted(c["case_id"] for c in cases)
    lanes: dict[str, int] = {}
    for case in cases:
        lanes[case["lane"]] = lanes.get(case["lane"], 0) + 1
    manifest = {
        "dataset": DATASET_NAME,
        "seed": SEED,
        "case_count": len(cases),
        "lanes": lanes,
        "splits": {"dev": sum(1 for c in cases if c["split"] == "dev"),
                   "holdout": sum(1 for c in cases if c["split"] == "holdout")},
        "sample_ids_sha256": hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest(),
        "files_sha256": {c["case_id"]: c["sha256"] for c in cases if c.get("sha256")},
        "synthetic_files_root": args.out,
        "external_root": str(external_root),
        "licenses": {
            "synthetic": "self-generated (fictional entities)",
            "sroie": "MIT (zzzDavid/ICDAR-2019-SROIE corrected data)",
            "xfund_zh": "CC BY-NC-SA 4.0 — internal evaluation only, do not redistribute",
            "librispeech": "CC BY 4.0 (openslr.org/12 test-clean)",
        },
        "notes": "holdout 结果只认单次全量跑 + 本 manifest 哈希一致;禁止 per-case best-of 聚合。",
    }
    (_HERE / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[suite] {len(cases)} cases  lanes={lanes}")
    print(f"[splits] dev={manifest['splits']['dev']} holdout={manifest['splits']['holdout']}")
    print(f"[manifest] sample_ids_sha256={manifest['sample_ids_sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
