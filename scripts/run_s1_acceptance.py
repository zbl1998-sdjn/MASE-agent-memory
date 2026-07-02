"""S1 验收 harness:SAPI 合成真语音 → 双 whisper lane 真跑 + 证据文件。

用法: python -X utf8 scripts/run_s1_acceptance.py [--runs-dir E:/MASE-runs]
前置: pip install "mase-memory[audio]"(faster-whisper);首跑自动下载权重。
产出: <runs>/s1_acceptance/<UTC时间戳>/evidence.{json,md}

判定(每个 lane 都必须满足,否则 verdict=FAIL / exit 1):
- extractions >= 1、infra_errors == 0
- 转写稿含全部锚词(不区分大小写)且锚词经 mase2_search_memory 可召回
- >= 1 条事实且 evidence 含 [HH:MM:SS] 时间戳
- 溯源链完整:事实 → media_extraction → media_asset → 资产文件存在
- device_fallback=True 不判 FAIL,但必须在证据中如实标注(CPU 降级)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ANCHORS = ("phoenix", "acme")
SAMPLE_SENTENCE = (
    "The phoenix project budget of four thousand two hundred euros "
    "was approved by acme corporation in the meeting."
)
TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}\]")


def check_dependency() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def make_sample(sample_dir: Path) -> Path:
    """Windows SAPI 离线合成真语音 WAV;无网络依赖。"""
    sample_dir.mkdir(parents=True, exist_ok=True)
    wav = sample_dir / "meeting.wav"
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{wav}'); "
        f"$s.Speak('{SAMPLE_SENTENCE}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=120)
    if not wav.exists() or wav.stat().st_size < 1000:
        raise RuntimeError(f"SAPI TTS 合成失败: {wav}")
    return wav


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


def run_lane(lane: str, whisper_model: str | None, samples: Path, out_dir: Path) -> dict:
    """单 whisper lane:独立 DB + 独立资产根,跑 ingest 并逐项断言。"""
    db_path = out_dir / f"lane_{lane}.db"
    asset_dir = out_dir / f"assets_{lane}"
    os.environ["MASE_DB_PATH"] = str(db_path)
    os.environ["MASE_MEDIA_ASSETS_DIR"] = str(asset_dir)
    from mase.multimodal.ingest import ingest_folder
    from mase_tools.memory.api import mase2_search_memory

    started = time.perf_counter()
    report = ingest_folder(samples, whisper_model=whisper_model, asset_root=asset_dir)
    elapsed = time.perf_counter() - started

    failures: list[str] = []
    if report.extractions < 1:
        failures.append(f"extractions={report.extractions} < 1")
    if report.infra_errors:
        failures.append(f"infra_errors={list(report.infra_errors)}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    log_row = conn.execute(
        "SELECT content FROM memory_log WHERE source_media_id IS NOT NULL LIMIT 1"
    ).fetchone()
    transcript = str(log_row["content"]) if log_row else ""
    fact_rows = conn.execute(
        "SELECT entity_key FROM entity_state WHERE source_media_id IS NOT NULL"
    ).fetchall()
    ext_row = conn.execute("SELECT result_json FROM media_extraction LIMIT 1").fetchone()
    conn.close()

    recall_hits: dict[str, bool] = {}
    for anchor in ANCHORS:
        in_transcript = anchor in transcript.lower()
        if not in_transcript:
            failures.append(f"anchor {anchor!r} not in transcript")
        hits = mase2_search_memory([anchor], limit=5)
        recall_hits[anchor] = any(anchor in str(h.get("content", "")).lower() for h in hits)
        if not recall_hits[anchor]:
            failures.append(f"anchor {anchor!r} not recalled")

    result_json = json.loads(ext_row["result_json"]) if ext_row else {}
    timestamped_facts = [
        f for f in result_json.get("candidate_facts", [])
        if TIMESTAMP_RE.search(str(f.get("evidence", "")))
    ]
    if not timestamped_facts:
        failures.append("no fact with [HH:MM:SS] evidence")
    asr_info = (result_json.get("metadata") or {}).get("asr") or {}

    chain_ok, chain_detail = _check_provenance_chain(db_path, asset_dir)
    if not chain_ok:
        failures.append(f"provenance chain broken: {chain_detail}")

    return {
        "lane": lane,
        "whisper_model": whisper_model or "large-v3",
        "elapsed_seconds": round(elapsed, 2),
        "report": {
            "processed": list(report.processed),
            "extractions": report.extractions,
            "facts_written": report.facts_written,
            "infra_errors": list(report.infra_errors),
            "warnings_sample": list(result_json.get("warnings", []))[:5],
        },
        "transcript_excerpt": transcript[:300],
        "facts": [row["entity_key"] for row in fact_rows],
        "timestamped_fact_count": len(timestamped_facts),
        "recall_hits": recall_hits,
        "asr": asr_info,
        "provenance_sample": chain_detail,
        "failures": failures,
    }


def _render_markdown(evidence: dict) -> str:
    lines = [
        "# S1 语音转写验收证据",
        "",
        f"- 时间(UTC): {evidence['timestamp_utc']}",
        f"- 样本句: {evidence['sample_sentence']}",
        f"- 锚词: {', '.join(evidence['anchors'])}",
        f"- 判定: **{evidence['verdict']}**",
        "",
        "| lane | whisper | 用时(s) | facts | 带时间戳事实 | 召回 | ASR device | fallback | failures |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for lane in evidence["lanes"]:
        recall = "/".join("Y" if v else "N" for v in lane["recall_hits"].values())
        asr = lane["asr"]
        lines.append(
            f"| {lane['lane']} | {lane['whisper_model']} | {lane['elapsed_seconds']} "
            f"| {lane['report']['facts_written']} | {lane['timestamped_fact_count']} | {recall} "
            f"| {asr.get('device', '?')}/{asr.get('compute_type', '?')} | {asr.get('device_fallback', '?')} "
            f"| {'; '.join(lane['failures']) or '-'} |"
        )
    lines += ["", "## 转写摘录", ""]
    for lane in evidence["lanes"]:
        lines += [f"### {lane['lane']}", "", "```", lane["transcript_excerpt"], "```", ""]
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", default=os.environ.get("MASE_RUNS_DIR", "../MASE-runs"))
    args = parser.parse_args()

    if not check_dependency():
        print('[missing] pip install "mase-memory[audio]"  (faster-whisper)')
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.runs_dir).resolve() / "s1_acceptance" / stamp
    samples = out_dir / "samples"
    make_sample(samples)

    lanes = [
        run_lane("largev3", None, samples, out_dir),
        run_lane("turbo", "large-v3-turbo", samples, out_dir),
    ]
    evidence = {
        "timestamp_utc": stamp,
        "sample_sentence": SAMPLE_SENTENCE,
        "anchors": list(ANCHORS),
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
