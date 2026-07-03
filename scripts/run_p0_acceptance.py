"""P0 治理层验收 harness:真模型 ingest → facts 双写 → 不变式机械复验 → fact sheet。

用法: python -X utf8 scripts/run_p0_acceptance.py [--runs-dir E:/MASE-runs]
前置: ollama 已 pull qwen2.5vl:7b(vision)与 config.json 的 doc_facts 模型;缺则 exit 2。
产出: <runs>/p0_acceptance/<UTC时间戳>/evidence.{json,md} + fact_sheets/*.md

判定(全部满足才 verdict=PASS / exit 0):
- extractions >= 2 且 infra_errors == 0(1 张 PNG + 1 个 2 页 PDF)
- facts_written >= 1 且 governance_warnings == 0 且 facts_governed == facts_written
- 不变式(真数据复验):每条 active fact 至少一条证据 span 非 NULL,且
  sha256(media_extraction.full_text[span_start:span_end]) == quote_hash
- fact sheet 导出非空

quarantined 计数如实报告但不判失败——定位失败进隔离本身就是治理在工作。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
# 强制置顶(remove+insert):site-packages 存在第三方同名包 `scripts`,
# 若仓根经 .pth 只挂在 sys.path 尾部,`import scripts.*` 会被其抢先命中。
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

import httpx

from scripts.run_s0_acceptance import make_samples  # noqa: E402 — 复用确定性样本


def _required_models() -> list[str]:
    config = json.loads((_ROOT / "config.json").read_text(encoding="utf-8"))
    doc_facts = config["models"]["doc_facts"]["model_name"]
    return ["qwen2.5vl:7b", doc_facts]


def check_models() -> list[str]:
    tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=10).json()
    have = {m["name"] for m in tags.get("models", [])}
    return [m for m in _required_models() if m not in have and f"{m}:latest" not in have]


def _verify_active_invariant(db_path: Path) -> tuple[list[str], dict[str, int]]:
    """机械复验不变式;返回 (失败列表, 状态计数)。"""
    failures: list[str] = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    status_counts = {
        str(r["status"]): int(r["n"])
        for r in conn.execute("SELECT status, COUNT(*) AS n FROM facts GROUP BY status")
    }
    for fact in conn.execute("SELECT fact_id, predicate FROM facts WHERE status='active'"):
        spans = conn.execute(
            """
            SELECT es.* FROM evidence_spans es
            JOIN fact_evidence fe ON fe.evidence_id = es.evidence_id
            WHERE fe.fact_id = ?
            """,
            (fact["fact_id"],),
        ).fetchall()
        located = [s for s in spans if s["span_start"] is not None and s["span_end"] is not None]
        if not located:
            failures.append(f"active {fact['predicate']} 无已定位证据")
            continue
        for span in located:
            if span["source_type"] != "media_extraction":
                failures.append(f"{fact['predicate']}: 非预期 source_type {span['source_type']}")
                continue
            row = conn.execute(
                "SELECT full_text FROM media_extraction WHERE id = ?", (int(span["source_id"]),)
            ).fetchone()
            if row is None:
                failures.append(f"{fact['predicate']}: extraction {span['source_id']} 不存在")
                continue
            matched = row["full_text"][span["span_start"] : span["span_end"]]
            digest = hashlib.sha256(matched.encode("utf-8")).hexdigest()
            if digest != span["quote_hash"]:
                failures.append(
                    f"{fact['predicate']}: quote_hash 不匹配(span 文本 {matched[:40]!r})"
                )
    conn.close()
    return failures, status_counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", default="E:/MASE-runs")
    args = parser.parse_args()

    missing = check_models()
    if missing:
        print(f"缺模型: {missing};请先 ollama pull。")
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.runs_dir) / "p0_acceptance" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = out_dir / "samples"
    make_samples(samples)

    db_path = out_dir / "p0.db"
    asset_dir = out_dir / "assets"
    os.environ["MASE_DB_PATH"] = str(db_path)
    os.environ["MASE_MEDIA_ASSETS_DIR"] = str(asset_dir)
    os.environ.setdefault("MASE_OLLAMA_KEEP_ALIVE", "0")

    from mase.multimodal.ingest import ingest_folder
    from scripts.export_fact_sheets import export_fact_sheets

    started = time.perf_counter()
    report = ingest_folder(samples, asset_root=asset_dir)
    elapsed = time.perf_counter() - started

    failures: list[str] = []
    if report.extractions < 2:
        failures.append(f"extractions={report.extractions} < 2")
    if report.infra_errors:
        failures.append(f"infra_errors={list(report.infra_errors)}")
    if report.facts_written < 1:
        failures.append("facts_written == 0")
    if report.governance_warnings:
        failures.append(f"governance_warnings={list(report.governance_warnings)}")
    if report.facts_governed != report.facts_written:
        failures.append(
            f"治理覆盖率不足: governed={report.facts_governed} != written={report.facts_written}"
        )

    invariant_failures, status_counts = _verify_active_invariant(db_path)
    failures.extend(invariant_failures)

    sheets = export_fact_sheets(out_dir=out_dir / "fact_sheets", db_path=db_path)
    if not sheets:
        failures.append("fact sheet 导出为空")

    verdict = "PASS" if not failures else "FAIL"
    evidence = {
        "verdict": verdict,
        "timestamp_utc": stamp,
        "elapsed_seconds": round(elapsed, 1),
        "models": _required_models(),
        "report": {
            "processed": list(report.processed),
            "extractions": report.extractions,
            "facts_written": report.facts_written,
            "facts_governed": report.facts_governed,
            "governance_warnings": list(report.governance_warnings),
            "infra_errors": list(report.infra_errors),
            "skipped": list(report.skipped),
        },
        "facts_by_status": status_counts,
        "fact_sheets": [str(p) for p in sheets],
        "failures": failures,
    }
    (out_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_lines = [
        f"# P0 治理层验收 — {verdict}",
        "",
        f"- 时间: {stamp}  用时: {elapsed:.1f}s",
        f"- 模型: {', '.join(_required_models())}",
        f"- extractions: {report.extractions}  facts_written: {report.facts_written}  "
        f"facts_governed: {report.facts_governed}",
        f"- facts 状态分布: {status_counts}",
        f"- fact sheets: {len(sheets)} 份 → {out_dir / 'fact_sheets'}",
        f"- 不变式复验: {'全部通过' if not invariant_failures else invariant_failures}",
        f"- failures: {failures or '-'}",
    ]
    (out_dir / "evidence.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"verdict={verdict} elapsed={elapsed:.1f}s facts={status_counts} out={out_dir}")
    for line in failures:
        print(f"  FAIL: {line}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
