"""multimodal_eval_v1 统一跑分器(确定性计分,逐例隔离,单次全量口径)。

用法:
    python -X utf8 benchmarks/multimodal_eval/run_eval.py \
        [--split holdout|dev|all] [--lanes synthetic,sroie,xfund_zh,librispeech] \
        [--limit N] [--vision-mode minicpm] [--whisper-model large-v3-turbo] \
        [--out-root E:/MASE-runs/eval_runs]

维度(全部确定性,无 LLM 评委):
- fulltext:   归一化锚串 ∈ 抽取全文
- facts:      某条已写入事实的 value 含 value_anchor
- recall:     mase2_search_memory 能召回锚串
- halluc_ok:  负例文件写入事实数 == 0
- provenance: 事实 → media_extraction → media_asset → 资产字节 链完整
- char_sim:   音频转写与参考转写的归一化字符相似度(SequenceMatcher,
              标注为 similarity 而非严格 WER/CER)

干扰问答(distractor_qa)与生成式 QA 需要 executor 生成,方差大,
v1 默认**不计分**,仅把问题清单写进 results 供后续 QA lane 使用。

反过拟合:默认 --split holdout 前会校验 manifest 文件哈希;不一致的
案例会被计入 manifest_mismatch 并在 summary 顶部醒目标注(结果与冻结
数据集不可比)。禁止 per-case best-of;一次调用产出一份完整 results。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_HERE = _REPO / "benchmarks" / "multimodal_eval"
_STRIP = set(" \t\n\r,，¥€$")


def _normalize(text: str) -> str:
    return "".join(ch for ch in str(text).casefold() if ch not in _STRIP)


def _contains(haystack: str, needle: str) -> bool:
    needle_n = _normalize(needle)
    return bool(needle_n) and needle_n in _normalize(haystack)


def _char_similarity(reference: str, hypothesis: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(reference), _normalize(hypothesis)).ratio()


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_case_file(case: dict[str, Any], synthetic_root: Path) -> Path:
    raw = Path(case["file"])
    return raw if raw.is_absolute() else synthetic_root / raw


def run_case(case: dict[str, Any], work_dir: Path, synthetic_root: Path,
             vision_mode: str | None, whisper_model: str | None) -> dict[str, Any]:
    """单案例:隔离 DB + 资产根 → ingest → 逐维计分。"""
    src = _resolve_case_file(case, synthetic_root)
    case_dir = work_dir / case["case_id"]
    ingest_dir = case_dir / "in"
    ingest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, ingest_dir / src.name)

    db_path = case_dir / "memory.db"
    os.environ["MASE_DB_PATH"] = str(db_path)
    os.environ["MASE_MEDIA_ASSETS_DIR"] = str(case_dir / "assets")

    from mase.multimodal.ingest import ingest_folder
    from mase_tools.memory.api import mase2_search_memory

    started = time.perf_counter()
    report = ingest_folder(ingest_dir, mode=vision_mode, whisper_model=whisper_model)
    elapsed = time.perf_counter() - started

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    log_row = conn.execute(
        "SELECT content FROM memory_log WHERE source_media_id IS NOT NULL LIMIT 1"
    ).fetchone()
    full_text = str(log_row["content"]) if log_row else ""
    fact_rows = conn.execute(
        "SELECT category, entity_key, entity_value, source_media_id FROM entity_state "
        "WHERE source_media_id IS NOT NULL"
    ).fetchall()
    ext_row = conn.execute("SELECT media_id FROM media_extraction LIMIT 1").fetchone()
    conn.close()

    fact_values = [str(r["entity_value"]) for r in fact_rows]

    dims: dict[str, Any] = {"elapsed_seconds": round(elapsed, 2),
                            "infra_error": bool(report.infra_errors)}
    if report.infra_errors:
        dims["infra_detail"] = list(report.infra_errors)

    anchors = case.get("anchors_fulltext") or []
    if anchors:
        hits = [a for a in anchors if _contains(full_text, a)]
        dims["fulltext_hit"] = len(hits)
        dims["fulltext_total"] = len(anchors)
        recall_hits = 0
        for anchor in anchors:
            found = mase2_search_memory([anchor], limit=5)
            if any(_contains(str(h.get("content", "")), anchor) for h in found):
                recall_hits += 1
        dims["recall_hit"] = recall_hits
        dims["recall_total"] = len(anchors)

    expected = case.get("expected_facts") or []
    if expected:
        fact_hits = sum(
            1 for ef in expected
            if any(any(_contains(v, a) for a in ef["value_anchors"]) for v in fact_values)
        )
        dims["facts_hit"] = fact_hits
        dims["facts_total"] = len(expected)

    if case.get("negative"):
        dims["halluc_fact_count"] = len(fact_rows)
        dims["halluc_ok"] = len(fact_rows) == 0

    reference = case.get("transcript") or case.get("tts_script")
    if case["modality"] == "audio" and reference:
        dims["char_similarity"] = round(_char_similarity(reference, full_text), 4)

    # 溯源链:抽一条事实走到资产字节;无事实但有抽取记录时按抽取记录验
    from mase_tools.media.asset_store import asset_path
    from mase_tools.memory.api import mase2_get_media_provenance

    media_id = int(fact_rows[0]["source_media_id"]) if fact_rows else (
        int(ext_row["media_id"]) if ext_row else None)
    if media_id is not None:
        chain = mase2_get_media_provenance(media_id)
        ok = bool(chain["asset"]) and bool(chain["extractions"]) and \
            asset_path(chain["asset"]["sha256"], root=Path(case_dir / "assets")) is not None
        dims["provenance_ok"] = ok

    shutil.rmtree(ingest_dir, ignore_errors=True)  # 保留 DB/资产供事后审计,删输入副本
    return dims


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(hit_key: str, total_key: str) -> float | None:
        hit = sum(r["dims"].get(hit_key, 0) for r in rows)
        total = sum(r["dims"].get(total_key, 0) for r in rows)
        return round(hit / total, 4) if total else None

    def bool_rate(key: str) -> float | None:
        vals = [r["dims"][key] for r in rows if key in r["dims"]]
        return round(sum(1 for v in vals if v) / len(vals), 4) if vals else None

    sims = [r["dims"]["char_similarity"] for r in rows if "char_similarity" in r["dims"]]
    return {
        "cases": len(rows),
        "infra_errors": sum(1 for r in rows if r["dims"].get("infra_error")),
        "fulltext_anchor_rate": rate("fulltext_hit", "fulltext_total"),
        "fact_anchor_rate": rate("facts_hit", "facts_total"),
        "recall_rate": rate("recall_hit", "recall_total"),
        "halluc_ok_rate": bool_rate("halluc_ok"),
        "provenance_ok_rate": bool_rate("provenance_ok"),
        "char_similarity_mean": round(sum(sims) / len(sims), 4) if sims else None,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="holdout", choices=["holdout", "dev", "all"])
    parser.add_argument("--lanes", default="synthetic,sroie,xfund_zh,librispeech")
    parser.add_argument("--limit", type=int, default=None, help="冒烟用;正式跑分禁用")
    parser.add_argument("--vision-mode", default=None)
    parser.add_argument("--whisper-model", default=None)
    parser.add_argument("--out-root", default="E:/MASE-runs/eval_runs")
    args = parser.parse_args()

    cases_path = _HERE / "cases.json"
    manifest = json.loads((_HERE / "manifest.json").read_text(encoding="utf-8"))
    all_cases = json.loads(cases_path.read_text(encoding="utf-8"))
    lanes = {lane.strip() for lane in args.lanes.split(",") if lane.strip()}
    synthetic_root = Path(manifest["synthetic_files_root"])

    selected = [
        c for c in all_cases
        if c["lane"] in lanes and (args.split == "all" or c["split"] == args.split)
    ]
    if args.limit:
        selected = selected[: args.limit]

    # manifest 完整性:重算文件哈希,不一致如实计数
    mismatched: list[str] = []
    for case in selected:
        path = _resolve_case_file(case, synthetic_root)
        if not path.is_file() or _sha256_file(path) != case.get("sha256"):
            mismatched.append(case["case_id"])

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_root).resolve() / f"{manifest['dataset']}_{args.split}_{stamp}"
    work_dir = out_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(selected, 1):
        if case["case_id"] in mismatched:
            rows.append({"case_id": case["case_id"], "lane": case["lane"],
                         "difficulty": case["difficulty"],
                         "dims": {"infra_error": True, "infra_detail": ["manifest_mismatch"]}})
            continue
        try:
            dims = run_case(case, work_dir, synthetic_root, args.vision_mode, args.whisper_model)
        except Exception as exc:
            dims = {"infra_error": True, "infra_detail": [f"{type(exc).__name__}: {exc}"]}
        rows.append({"case_id": case["case_id"], "lane": case["lane"],
                     "difficulty": case["difficulty"], "dims": dims})
        print(f"[{index}/{len(selected)}] {case['case_id']} {dims}")

    by_lane = {lane: _aggregate([r for r in rows if r["lane"] == lane])
               for lane in sorted({r["lane"] for r in rows})}
    by_difficulty = {f"L{d}": _aggregate([r for r in rows if r["difficulty"] == d])
                     for d in sorted({r["difficulty"] for r in rows})}
    results = {
        "dataset": manifest["dataset"],
        "sample_ids_sha256": manifest["sample_ids_sha256"],
        "split": args.split,
        "lanes": sorted(lanes),
        "limit": args.limit,
        "vision_mode": args.vision_mode,
        "whisper_model": args.whisper_model or "large-v3(默认)",
        "timestamp_utc": stamp,
        "manifest_mismatch": mismatched,
        "aggregate": {"overall": _aggregate(rows), "by_lane": by_lane, "by_difficulty": by_difficulty},
        "qa_not_scored_note": "qa/distractor_qa 需 executor 生成,v1 默认不计分;清单见 cases.json",
        "rows": rows,
    }
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [f"# {manifest['dataset']} 跑分 ({args.split}, {stamp})", ""]
    if args.limit:
        lines.append(f"> ⚠️ --limit {args.limit} 冒烟跑,不作为正式成绩。")
    if mismatched:
        lines.append(f"> ⚠️ {len(mismatched)} 例与冻结 manifest 哈希不一致,结果不可与历史比较: {mismatched[:5]}...")
    lines += ["", "| 维度 | overall |" + "".join(f" {k} |" for k in by_lane), "|---|---|" + "---|" * len(by_lane)]
    for metric in ("cases", "infra_errors", "fulltext_anchor_rate", "fact_anchor_rate",
                   "recall_rate", "halluc_ok_rate", "provenance_ok_rate", "char_similarity_mean"):
        row = f"| {metric} | {results['aggregate']['overall'].get(metric)} |"
        row += "".join(f" {agg.get(metric)} |" for agg in by_lane.values())
        lines.append(row)
    lines += ["", "## by difficulty", ""]
    for level, agg in by_difficulty.items():
        lines.append(f"- {level}: {json.dumps(agg, ensure_ascii=False)}")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[results] {out_dir / 'results.json'}")
    print(f"[overall] {json.dumps(results['aggregate']['overall'], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
