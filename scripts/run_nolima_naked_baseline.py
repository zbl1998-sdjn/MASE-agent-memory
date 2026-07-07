"""NoLiMa 真裸基线:官方模板 + 全文直喂,零辅助(取证纪要 2026-07-07)。

背景:旧"裸基线"复用 MASE executor(num_ctx 8192,32k 全文被截 → 4 月 1.79%
是截断伪影);其 runner 后又在版本控制外加了候选名单注入(不再是裸协议)。
本脚本是协议上干净的裸对照:`task_template.format(haystack=全文, question=q)`
经 ollama 原始 chat 直喂(num_ctx 显式 32768),无检索、无候选、无 MASE。

口径注:num_ctx=32768 而 prompt = 32768 token 上下文 + ~90 token 模板,超出
部分由 ollama 从头部截断——depth50 的针不受影响,如实记录。

用法:
    python -X utf8 scripts/run_nolima_naked_baseline.py [--limit-tests N] [--run-dir DIR]
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import ollama

ROOT = Path(__file__).resolve().parents[1]
_NOLIMA_DIR = ROOT / "benchmarks" / "external-benchmarks" / "NoLiMa"
# 无条件前置:editable install 的 .pth 会把 ROOT 挂在 sys.path 靠后,脚本目录
# (scripts/,自带 benchmarks 子包)反而在前,导致 benchmarks.runner 解析错包;
# NoLiMa 目录上榜是因为 official runner 以 top-level 方式 import data.book_haystack。
for p in (str(_NOLIMA_DIR), str(ROOT), str(ROOT / "src")):
    while p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

_OFFICIAL_PATH = ROOT / "benchmarks" / "external-benchmarks" / "NoLiMa" / "run_mase_official.py"
_spec = _ilu.spec_from_file_location("nolima_official", str(_OFFICIAL_PATH))
_official = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
assert _spec and _spec.loader
sys.modules["nolima_official"] = _official
_spec.loader.exec_module(_official)  # type: ignore[union-attr]

MODEL = "qwen2.5:7b"
NUM_CTX = 32768


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NoLiMa naked baseline (no retrieval, no aid)")
    ext = ROOT / "benchmarks" / "external-benchmarks" / "NoLiMa"
    p.add_argument("--needle-set-path", default=str(ext / "data" / "needlesets" / "needle_set_ONLYDirect.json"))
    p.add_argument("--haystack-dir", default=str(ext / "data" / "haystack" / "rand_shuffle"))
    p.add_argument("--context-length", type=int, default=32768)
    p.add_argument("--depth-percent", type=float, default=50.0)
    p.add_argument("--limit-tests", type=int, default=None)
    p.add_argument("--limit-haystacks", type=int, default=2)
    p.add_argument("--base-seed", type=int, default=42)
    p.add_argument("--metric", default="contains")
    p.add_argument("--run-dir", default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    expanded_tests = _official.load_needle_set(Path(args.needle_set_path), base_seed=args.base_seed)
    if args.limit_tests is not None:
        expanded_tests = expanded_tests[: args.limit_tests]
    haystack_paths = sorted(
        p for p in Path(args.haystack_dir).iterdir() if p.suffix.lower() == ".txt"
    )[: args.limit_haystacks]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.run_dir) if args.run_dir else (
        Path("E:/MASE-runs/results/external") / f"nolima_naked_{args.context_length}_{stamp}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    _, encode_tokens, decode_tokens = _official.build_tokenizer("cl100k_base")
    # 驻留 runner 的 num_ctx 是加载期参数:热实例若以小窗加载,ollama 会静默
    # 截断后续大窗请求;且 stop 后立刻请求会撞上旧 runner 未释放的显存,新
    # runner 被迫按剩余显存把 ctx 砍半(冒烟实录 2026-07-07:恒 16386)。
    # 先卸载 + 等显存真正回收,再按本次 num_ctx 冷加载。
    subprocess.run(["ollama", "stop", MODEL], capture_output=True, check=False)
    time.sleep(8)
    client = ollama.Client(timeout=600)
    results = []
    passed = 0
    truncation_warnings = 0
    for h_idx, h_path in enumerate(haystack_paths):
        haystack = _official.Utf8BookHaystack(str(h_path))
        for test in expanded_tests:
            np.random.seed(test.seed + h_idx)
            selected = None
            needle, rq, gold = test.needle, test.retrieval_question, list(test.gold_answers)
            if "{CHAR}" in needle:
                selected = str(np.random.choice(test.character_set))
                needle = needle.replace("{CHAR}", selected)
                rq = rq.replace("{CHAR}", selected)
                if not gold:
                    gold = [selected]
            placement = haystack.generate_w_needle_placement(
                needle=needle,
                token_count_func=lambda t: len(encode_tokens(t)),
                encoding_func=encode_tokens,
                decoding_func=decode_tokens,
                context_length=args.context_length,
                shift=0,
                depth=args.depth_percent / 100.0,
                static_depth=-1.0,
                distractor=test.distractor,
            )
            prompt = test.task_template.format(haystack=str(placement["text"]), question=rq)
            messages = []
            if str(test.system_prompt or "").strip():
                messages.append({"role": "system", "content": test.system_prompt.strip()})
            messages.append({"role": "user", "content": prompt})

            started = time.perf_counter()
            error = None
            raw = ""
            prompt_eval = None
            try:
                reply = client.chat(
                    model=MODEL,
                    messages=messages,
                    options={"num_ctx": NUM_CTX, "temperature": 0.0, "num_predict": 64},
                )
                raw = str((reply.get("message") or {}).get("content") or "")
                prompt_eval = reply.get("prompt_eval_count")
            except Exception as exc:  # noqa: BLE001 - 单例失败记 0 分继续跑批
                error = f"{type(exc).__name__}: {exc}"
            truncated = prompt_eval is not None and prompt_eval < args.context_length * 0.8
            truncation_warnings += bool(truncated)
            value = _official.evaluate_metric(args.metric, raw, gold) if not error else 0
            passed += value
            results.append({
                "test_name": test.test_name,
                "haystack_name": h_path.name,
                "depth_percent": args.depth_percent,
                "gold_answers": gold,
                "response": raw[:200],
                "metric_value": value,
                "prompt_eval_count": prompt_eval,
                "truncation_suspected": truncated,
                "elapsed_s": round(time.perf_counter() - started, 2),
                "error": error,
            })
            print(f"[{len(results)}] {test.test_name} {h_path.name} -> {value}"
                  f" (ate={prompt_eval} tok, {results[-1]['elapsed_s']}s)", flush=True)

    total = len(results)
    summary = {
        "protocol": "naked_full_context",
        "model": MODEL,
        "num_ctx": NUM_CTX,
        "context_length": args.context_length,
        "depth_percent": args.depth_percent,
        "metric": args.metric,
        "processed": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else None,
        "truncation_warnings": truncation_warnings,
    }
    (run_dir / "naked.results.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"[naked-baseline] {json.dumps(summary, ensure_ascii=False)}")
    print(f"[results] {run_dir / 'naked.results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
