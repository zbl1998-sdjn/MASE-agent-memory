"""S2 验收 harness:真起 sidecar 服务 → httpx multipart 上传 → 记忆召回判据。

用法: python -X utf8 scripts/run_s2_acceptance.py [--runs-dir E:/MASE-runs]
前置: ollama 已 pull qwen2.5vl:7b(缺 → exit 2 给指引)。
产出: <runs>/s2_acceptance/<UTC时间戳>/evidence.{json,md}

PASS 判据(本地 lane,全部必须):
- 上传 200,extraction.facts 非空,full_text_excerpt 含锚词,dedup=false
- 重复上传 dedup=true
- POST /v1/memory/recall 能召回锚词
- 溯源链:事实 → media_extraction → media_asset → 资产字节
诊断字段(不判 PASS):/v1/chat/completions 的生成回答(7B 措辞方差大)。
云 lane:未显式批准云模型或 vision provider 非云 → 如实记 skipped,不算 FAIL。
"""
from __future__ import annotations

import argparse
import json
import os
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

import httpx

VISION_MODEL = "qwen2.5vl:7b"
ANCHORS = ("ACME-INV-2026-001", "4200")
PORT = 8899
PDF_DPI = 150


def check_models() -> list[str]:
    tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=10).json()
    have = {m["name"] for m in tags.get("models", [])}
    return [] if (VISION_MODEL in have or f"{VISION_MODEL}:latest" in have) else [VISION_MODEL]


def make_sample(sample_dir: Path) -> Path:
    import fitz

    sample_dir.mkdir(parents=True, exist_ok=True)
    png = sample_dir / "invoice.png"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "INVOICE ACME-INV-2026-001", fontsize=18)
    page.insert_text((72, 110), "Vendor: ACME GmbH   Total: 4200 EUR", fontsize=14)
    page.get_pixmap(dpi=PDF_DPI).save(str(png))
    doc.close()
    return png


def start_server(port: int, env_overrides: dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "uvicorn",
         "integrations.openai_compat.server:app", "--host", "127.0.0.1", "--port", str(port)],
        env={**os.environ, **env_overrides}, cwd=str(_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError("sidecar 提前退出")
        time.sleep(1.0)
    proc.terminate()
    raise RuntimeError("sidecar 60s 未就绪")


def _check_provenance_chain(db_path: Path, asset_dir: Path) -> tuple[bool, str]:
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
    if chain["asset"] is None or not chain["extractions"]:
        return False, f"fact {fact['entity_key']}: chain rows missing"
    sha = chain["asset"]["sha256"]
    stored = asset_path(sha, root=asset_dir)
    if stored is None:
        return False, f"asset bytes missing for sha256={sha[:12]}..."
    return True, f"{fact['category']}.{fact['entity_key']} -> extraction -> {sha[:12]}... -> {stored.name}"


def run_local_lane(out_dir: Path, sample: Path) -> dict:
    db_path = out_dir / "lane_local.db"
    asset_dir = out_dir / "assets_local"
    env = {
        "MASE_DB_PATH": str(db_path),
        "MASE_MEDIA_ASSETS_DIR": str(asset_dir),
        "MASE_RUNS_DIR": str(out_dir),
    }
    # 本进程做溯源/召回校验时也要指向同一套存储
    os.environ.update(env)
    proc = start_server(PORT, env)
    failures: list[str] = []
    base = f"http://127.0.0.1:{PORT}"
    try:
        started = time.perf_counter()
        with open(sample, "rb") as fh:
            resp = httpx.post(
                f"{base}/v1/mase/media/upload",
                files={"file": (sample.name, fh, "image/png")},
                timeout=300,
            )
        elapsed = time.perf_counter() - started
        if resp.status_code != 200:
            failures.append(f"upload status={resp.status_code}: {resp.text[:200]}")
            return {"lane": "local", "failures": failures}
        body = resp.json()
        excerpt = str(body["extraction"]["full_text_excerpt"])
        if not body["extraction"]["facts"]:
            failures.append("no facts extracted")
        for anchor in ANCHORS:
            if anchor.lower() not in excerpt.lower():
                failures.append(f"anchor {anchor!r} not in excerpt")
        if body["deduplicated"]:
            failures.append("first upload flagged deduplicated")

        with open(sample, "rb") as fh:
            resp2 = httpx.post(
                f"{base}/v1/mase/media/upload",
                files={"file": (sample.name, fh, "image/png")},
                timeout=120,
            )
        if resp2.status_code != 200 or not resp2.json().get("deduplicated"):
            failures.append("second upload not deduplicated")

        recall = httpx.post(
            f"{base}/v1/memory/recall",
            json={"query": ANCHORS[0], "top_k": 5},
            timeout=60,
        )
        recall_text = json.dumps(recall.json(), ensure_ascii=False) if recall.status_code == 200 else ""
        recall_hit = ANCHORS[0].lower() in recall_text.lower()
        if not recall_hit:
            failures.append(f"recall status={recall.status_code}, anchor missing")

        chat_answer = ""
        try:
            chat = httpx.post(
                f"{base}/v1/chat/completions",
                json={"model": "mase", "messages": [
                    {"role": "user", "content": "What is the total of invoice ACME-INV-2026-001?"}]},
                timeout=180,
            )
            chat_answer = str(chat.json()["choices"][0]["message"]["content"])[:300]
        except Exception as exc:
            chat_answer = f"(chat diagnostic failed: {exc})"

        chain_ok, chain_detail = _check_provenance_chain(db_path, asset_dir)
        if not chain_ok:
            failures.append(f"provenance chain broken: {chain_detail}")

        return {
            "lane": "local",
            "vision_model": VISION_MODEL,
            "elapsed_seconds": round(elapsed, 2),
            "upload_facts": body["extraction"]["facts"],
            "excerpt": excerpt[:200],
            "recall_hit": recall_hit,
            "chat_answer_diagnostic": chat_answer,
            "provenance_sample": chain_detail,
            "failures": failures,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


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
    out_dir = Path(args.runs_dir).resolve() / "s2_acceptance" / stamp
    sample = make_sample(out_dir / "samples")

    lanes = [run_local_lane(out_dir, sample)]

    # 云 lane:只有显式批准 + vision agent 配了云 provider 才跑;否则如实 skipped。
    cloud_note = "skipped (MASE_ALLOW_CLOUD_MODELS not set or vision provider is local)"
    allow_cloud = str(os.environ.get("MASE_ALLOW_CLOUD_MODELS") or "").strip().lower() in {"1", "true", "yes"}
    if allow_cloud:
        from mase.model_interface import ModelInterface

        provider = str(ModelInterface().get_effective_agent_config("vision").get("provider") or "ollama")
        if provider in {"openai", "anthropic"}:
            cloud_note = f"configured provider={provider}; 手动以云配置重跑本 harness 取证"
    evidence = {
        "timestamp_utc": stamp,
        "anchors": list(ANCHORS),
        "lanes": lanes,
        "cloud_lane": cloud_note,
        "verdict": "PASS" if not any(lane["failures"] for lane in lanes) else "FAIL",
    }
    (out_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    lane = lanes[0]
    md = [
        "# S2 交互式上传验收证据", "",
        f"- 时间(UTC): {stamp}",
        f"- 判定: **{evidence['verdict']}**",
        f"- 云 lane: {cloud_note}", "",
        f"- 上传抽取用时: {lane.get('elapsed_seconds')}s({lane.get('vision_model')})",
        f"- facts: {json.dumps(lane.get('upload_facts'), ensure_ascii=False)[:300]}",
        f"- 召回命中: {lane.get('recall_hit')}",
        f"- 溯源: {lane.get('provenance_sample')}",
        f"- chat 诊断回答(不判分): {lane.get('chat_answer_diagnostic')}",
        f"- failures: {lane.get('failures') or '-'}",
    ]
    (out_dir / "evidence.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"[evidence] {out_dir / 'evidence.json'}  verdict={evidence['verdict']}")
    for failure in lane["failures"]:
        print(f"  [FAIL] {failure}")
    return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
