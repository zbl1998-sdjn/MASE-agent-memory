"""NoLiMa runner that uses MASE's true chunk+retrieve pipeline.

Difference vs run_mase_official.py:
- run_mase_official.py passes the entire haystack as fact_sheet -> tests the
  base model's long-context capability (or fails when num_ctx truncates).
- This runner chunks the haystack, ingests via notetaker.write, retrieves
  top-k via notetaker.search, then calls executor with only retrieved chunks.
  This is the actual MASE V2 pitch.
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Reuse helpers from the official runner — load by file path because the
# `external-benchmarks` directory contains a hyphen and isn't a Python package.
_OFFICIAL_PATH = Path(__file__).with_name("run_mase_official.py")
_spec = _ilu.spec_from_file_location("nolima_official", str(_OFFICIAL_PATH))
_official = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
assert _spec and _spec.loader
sys.modules["nolima_official"] = _official  # required for dataclass module lookup
_spec.loader.exec_module(_official)  # type: ignore[union-attr]
Utf8BookHaystack = _official.Utf8BookHaystack
build_executor_question = _official.build_executor_question
build_tokenizer = _official.build_tokenizer
evaluate_metric = _official.evaluate_metric
load_needle_set = _official.load_needle_set

from benchmarks.runner import _aggregate_call_log  # type: ignore
from mase import MASESystem


def _resolve_runs_dir() -> Path:
    raw = os.environ.get("MASE_RUNS_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (ROOT.parent / "MASE-runs").resolve()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--needle-set-path", required=True)
    p.add_argument("--haystack-dir", required=True)
    p.add_argument("--context-length", type=int, required=True)
    p.add_argument("--encoding-name", default="cl100k_base")
    p.add_argument("--shift", type=int, default=0)
    p.add_argument("--static-depth", type=float, default=-1.0)
    p.add_argument("--document-depth-percent-min", type=float, default=0.0)
    p.add_argument("--document-depth-percent-max", type=float, default=100.0)
    p.add_argument("--document-depth-percent-intervals", type=int, default=1)
    p.add_argument("--limit-tests", type=int, default=None)
    p.add_argument("--limit-haystacks", type=int, default=None)
    p.add_argument("--base-seed", type=int, default=42)
    p.add_argument("--metric", default="contains_any")
    p.add_argument("--executor-role", default="general", choices=["general", "reasoning"])
    p.add_argument("--run-dir", default=None)
    # chunked-specific
    p.add_argument("--chunk-chars", type=int, default=900, help="haystack chunk size (chars)")
    p.add_argument("--chunk-overlap", type=int, default=120, help="chunk overlap (chars)")
    p.add_argument("--top-k", type=int, default=8, help="retrieved chunks count")
    return p.parse_args()


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    if size <= 0:
        return [text]
    step = max(1, size - max(0, overlap))
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        chunks.append(text[i : i + size])
        if i + size >= n:
            break
        i += step
    return chunks


def ingest_and_retrieve(
    system: MASESystem,
    haystack_text: str,
    question: str,
    chunk_chars: int,
    chunk_overlap: int,
    top_k: int,
) -> tuple[str, int, int]:
    """Wipe notetaker DB, ingest chunks, retrieve top-k -> fact_sheet."""
    nt = system.notetaker_agent
    # Wipe table for fresh per-test isolation
    with nt._connect() as conn:
        try:
            conn.execute("DELETE FROM memory_log")
            conn.commit()
        except Exception:
            pass
    chunks = chunk_text(haystack_text, chunk_chars, chunk_overlap)
    for idx, chunk in enumerate(chunks):
        nt.write(
            user_query=f"document_excerpt_{idx:04d}",
            assistant_response=chunk,
            summary=chunk[:160].replace("\n", " "),
            metadata={"chunk_index": idx},
        )
    # Retrieve
    keywords = [w for w in question.replace("?", " ").split() if len(w) >= 3][:8]
    hits = nt.search(keywords or [question], full_query=question, limit=top_k)
    pieces: list[str] = []
    for h in hits:
        body = (h.get("content") or "").split("Assistant:", 1)
        text = body[1].strip() if len(body) > 1 else (h.get("content") or "")
        if text and "Summary:" in text:
            text = text.split("Summary:", 1)[0].strip()
        pieces.append(text)
    fact_sheet = "\n---\n".join(pieces) if pieces else "No relevant memory."
    return fact_sheet, len(chunks), len(hits)


def main() -> int:
    args = parse_args()
    needle_set_path = Path(args.needle_set_path).resolve()
    haystack_dir = Path(args.haystack_dir).resolve()

    expanded_tests = load_needle_set(needle_set_path, base_seed=args.base_seed)
    if args.limit_tests is not None:
        expanded_tests = expanded_tests[: args.limit_tests]

    haystack_paths = sorted(p for p in haystack_dir.iterdir() if p.suffix.lower() == ".txt")
    if args.limit_haystacks is not None:
        haystack_paths = haystack_paths[: args.limit_haystacks]

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_run_dir = (
        _resolve_runs_dir()
        / "external-benchmarks"
        / "NoLiMa"
        / "outputs"
        / f"mase-chunked-{needle_set_path.stem}-{args.context_length}-{timestamp}"
    )
    run_dir = Path(args.run_dir).resolve() if args.run_dir else default_run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    results_path = run_dir / "nolima.results.json"
    summary_path = run_dir / "nolima.summary.json"

    # Per-run isolated memory dir to avoid clobbering production memory
    iso_mem = Path(tempfile.mkdtemp(prefix="mase_nolima_chunked_"))
    os.environ["MASE_MEMORY_DIR"] = str(iso_mem)
    os.environ["MASE_BENCHMARK_MODE"] = "1"
    os.environ["MASE_TASK_TYPE"] = "long_context_qa"

    _, encode_tokens, decode_tokens = build_tokenizer(args.encoding_name)
    system = MASESystem()
    results: list[dict[str, Any]] = []

    try:
        for h_idx, h_path in enumerate(haystack_paths):
            haystack = Utf8BookHaystack(str(h_path))
            for test in expanded_tests:
                np.random.seed(test.seed + h_idx)
                for depth_percent in np.linspace(
                    args.document_depth_percent_min,
                    args.document_depth_percent_max,
                    args.document_depth_percent_intervals,
                ):
                    selected_character = None
                    needle = test.needle
                    rq = test.retrieval_question
                    gold = list(test.gold_answers)
                    if "{CHAR}" in needle:
                        selected_character = str(np.random.choice(test.character_set))
                        needle = needle.replace("{CHAR}", selected_character)
                        rq = rq.replace("{CHAR}", selected_character)
                        if not gold:
                            gold = [selected_character]
                    placement = haystack.generate_w_needle_placement(
                        needle=needle,
                        token_count_func=lambda t: len(encode_tokens(t)),
                        encoding_func=encode_tokens,
                        decoding_func=decode_tokens,
                        context_length=args.context_length,
                        shift=args.shift,
                        depth=float(depth_percent) / 100.0,
                        static_depth=args.static_depth,
                        distractor=test.distractor,
                    )
                    question = build_executor_question(
                        system_prompt=test.system_prompt,
                        task_template=test.task_template,
                        retrieval_question=rq,
                    )

                    system.model_interface.reset_call_log()
                    started = time.perf_counter()
                    raw = ""
                    error = None
                    fact_sheet = ""
                    n_chunks = n_hits = 0
                    try:
                        fact_sheet, n_chunks, n_hits = ingest_and_retrieve(
                            system,
                            str(placement["text"]),
                            rq,
                            args.chunk_chars,
                            args.chunk_overlap,
                            args.top_k,
                        )
                        raw = system.call_executor(
                            user_question=question,
                            fact_sheet=fact_sheet,
                            allow_general_knowledge=False,
                            task_type="grounded_answer",
                            use_memory=True,
                            executor_role=args.executor_role,
                        )
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"

                    metrics = _aggregate_call_log(system.model_interface.get_call_log())
                    metrics["wall_clock_seconds"] = round(time.perf_counter() - started, 6)
                    metric_value = evaluate_metric(args.metric, raw, gold) if not error else 0
                    row = {
                        "test_name": test.test_name,
                        "haystack_name": h_path.name,
                        "context_length": args.context_length,
                        "depth_percent": round(float(depth_percent), 3),
                        "needle": needle,
                        "retrieval_question": rq,
                        "gold_answers": gold,
                        "selected_character": selected_character,
                        "response": raw,
                        "metric": args.metric,
                        "metric_value": metric_value,
                        "chunked_meta": {
                            "n_chunks": n_chunks,
                            "n_hits": n_hits,
                            "fact_sheet_chars": len(fact_sheet),
                        },
                        "metrics": metrics,
                        "error": error,
                    }
                    results.append(row)

        # summary
        passed = sum(1 for r in results if r["metric_value"])
        total = len(results)
        by_test: dict[str, list[int]] = {}
        for r in results:
            by_test.setdefault(r["test_name"], []).append(int(r["metric_value"]))
        summary = {
            "accuracy": round(passed / total, 4) if total else 0.0,
            "passed": passed,
            "processed": total,
            "by_test": {k: {"acc": round(sum(v) / len(v), 4), "n": len(v)} for k, v in by_test.items()},
        }
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_path.write_text(
            json.dumps(
                {
                    "needle_set_path": str(needle_set_path),
                    "haystack_dir": str(haystack_dir),
                    "context_length": args.context_length,
                    "executor_role": args.executor_role,
                    "chunk_chars": args.chunk_chars,
                    "chunk_overlap": args.chunk_overlap,
                    "top_k": args.top_k,
                    "summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[chunked] {needle_set_path.stem} ctx={args.context_length} acc={summary['accuracy']:.4f} {passed}/{total}")
        return 0
    finally:
        try:
            shutil.rmtree(iso_mem, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
