"""S0 验收 harness:双模型 lane 真跑 + 证据文件。

用法: python -X utf8 scripts/run_s0_acceptance.py [--runs-dir E:/MASE-runs]
前置: ollama 已 pull qwen2.5vl:7b 和 minicpm-v4.5;缺则 exit 2 并给指引。
产出: <runs>/s0_acceptance/<UTC时间戳>/evidence.{json,md}

判定(每个 lane 都必须满足,否则 verdict=FAIL / exit 1):
- extractions >= 2(1 张 PNG + 1 个 2 页 PDF)
- infra_errors == 0
- 两个锚词均可经 mase2_search_memory 召回
- 溯源链完整:事实 → media_extraction → media_asset → 资产文件存在
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import httpx

REQUIRED_MODELS = ("qwen2.5vl:7b", "minicpm-v4.5")
ANCHORS = ("ACME-INV-2026-001", "4200")
PDF_DPI = 150


def check_models() -> list[str]:
    """探测本地 Ollama 已 pull 的模型;返回缺失列表。"""
    tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=10).json()
    have = {m["name"] for m in tags.get("models", [])}
    return [m for m in REQUIRED_MODELS if m not in have and f"{m}:latest" not in have]


def make_samples(sample_dir: Path) -> None:
    """确定性样本:发票样式 PNG + 2 页 PDF,锚词渲染在图面上。"""
    import fitz

    sample_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "INVOICE ACME-INV-2026-001", fontsize=18)
    page.insert_text((72, 110), "Vendor: ACME GmbH   Total: 4200 EUR", fontsize=14)
    page.get_pixmap(dpi=PDF_DPI).save(str(sample_dir / "invoice.png"))
    doc.close()

    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Contract ACME-INV-2026-001 page one", fontsize=14)
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Payment terms: 4200 EUR net 30", fontsize=14)
    doc.save(str(sample_dir / "contract.pdf"))
    doc.close()


def _check_provenance_chain(db_path: Path, asset_dir: Path) -> tuple[bool, str]:
    """抽样一条带 source_media_id 的事实,沿链走到资产文件。"""
    from mase_tools.media.asset_store import asset_path
    from mase_tools.memory.api import mase2_get_media_provenance

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    fact = conn.execute(
        "SELECT category, entity_key, source_media_id FROM entity_state "
        "WHERE source_media_id IS NOT NULL LIMIT 1"
    ).fetchone()
    conn.close()
    if fact is None:
        return False, "no fact with source_media_id found"
    chain = mase2_get_media_provenance(int(fact["source_media_id"]))
    if chain["asset"] is None:
        return False, f"fact {fact['entity_key']}: media_asset row missing"
    if not chain["extractions"]:
        return False, f"fact {fact['entity_key']}: no media_extraction rows"
    sha = chain["asset"]["sha256"]
    stored = asset_path(sha, root=asset_dir)
    if stored is None:
        return False, f"asset bytes missing for sha256={sha[:12]}..."
    return True, f"{fact['category']}.{fact['entity_key']} -> extraction -> {sha[:12]}... -> {stored.name}"


def run_lane(lane: str, mode: str | None, samples: Path, out_dir: Path) -> dict:
    """单模型 lane:独立 DB + 独立资产根,跑 ingest 并逐项断言。"""
    db_path = out_dir / f"lane_{lane}.db"
    asset_dir = out_dir / f"assets_{lane}"
    os.environ["MASE_DB_PATH"] = str(db_path)
    os.environ["MASE_MEDIA_ASSETS_DIR"] = str(asset_dir)
    from mase.multimodal.ingest import ingest_folder
    from mase_tools.memory.api import mase2_search_memory

    started = time.perf_counter()
    report = ingest_folder(samples, mode=mode, asset_root=asset_dir)
    elapsed = time.perf_counter() - started

    failures: list[str] = []
    if report.extractions < 2:
        failures.append(f"extractions={report.extractions} < 2")
    if report.infra_errors:
        failures.append(f"infra_errors={list(report.infra_errors)}")

    recall_hits: dict[str, bool] = {}
    for anchor in ANCHORS:
        hits = mase2_search_memory([anchor], limit=5)
        recall_hits[anchor] = any(anchor in str(h.get("content", "")) for h in hits)
        if not recall_hits[anchor]:
            failures.append(f"anchor {anchor!r} not recalled")

    chain_ok, chain_detail = _check_provenance_chain(db_path, asset_dir)
    if not chain_ok:
        failures.append(f"provenance chain broken: {chain_detail}")

    return {
        "lane": lane,
        "mode": mode,
        "elapsed_seconds": round(elapsed, 2),
        "report": {
            "processed": list(report.processed),
            "extractions": report.extractions,
            "facts_written": report.facts_written,
            "skipped": list(report.skipped),
            "infra_errors": list(report.infra_errors),
        },
        "recall_hits": recall_hits,
        "provenance_sample": chain_detail,
        "failures": failures,
    }


def _render_markdown(evidence: dict) -> str:
    lines = [
        "# S0 多模态摄取验收证据",
        "",
        f"- 时间(UTC): {evidence['timestamp_utc']}",
        f"- PDF DPI: {evidence['pdf_dpi']}",
        f"- 锚词: {', '.join(evidence['anchors'])}",
        f"- 判定: **{evidence['verdict']}**",
        "",
        "| lane | mode | 用时(s) | extractions | facts | 召回 | 溯源 | failures |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lane in evidence["lanes"]:
        recall = "/".join("Y" if v else "N" for v in lane["recall_hits"].values())
        lines.append(
            f"| {lane['lane']} | {lane['mode'] or 'default'} | {lane['elapsed_seconds']} "
            f"| {lane['report']['extractions']} | {lane['report']['facts_written']} "
            f"| {recall} | {lane['provenance_sample']} | {'; '.join(lane['failures']) or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", default=os.environ.get("MASE_RUNS_DIR", "../MASE-runs"))
    args = parser.parse_args()

    missing = check_models()
    if missing:
        for m in missing:
            print(f"[missing] ollama pull {m}")
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.runs_dir).resolve() / "s0_acceptance" / stamp
    samples = out_dir / "samples"
    make_samples(samples)

    lanes = [
        run_lane("qwen25vl", None, samples, out_dir),
        run_lane("minicpm", "minicpm", samples, out_dir),
    ]
    evidence = {
        "timestamp_utc": stamp,
        "pdf_dpi": PDF_DPI,
        "anchors": list(ANCHORS),
        "models": list(REQUIRED_MODELS),
        "lanes": lanes,
        "verdict": "PASS" if not any(lane["failures"] for lane in lanes) else "FAIL",
    }
    (out_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "evidence.md").write_text(_render_markdown(evidence), encoding="utf-8")

    print(f"[evidence] {out_dir / 'evidence.json'}  verdict={evidence['verdict']}")
    for lane in lanes:
        for failure in lane["failures"]:
            print(f"  [FAIL {lane['lane']}] {failure}")
    return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
