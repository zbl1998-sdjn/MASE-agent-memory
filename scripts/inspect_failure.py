"""Inspect a single failing LV-Eval sample end-to-end.

Usage:
    python scripts/inspect_failure.py <config> <index>
e.g.
    python scripts/inspect_failure.py hotpotwikiqa_mixup_16k 0
"""
import os, sys, io, json, tempfile, shutil, traceback
sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")
os.environ.setdefault("MASE_CONFIG_PATH", r"E:\MASE-demo\config.json")

from benchmarks.registry import load_benchmark_samples
from benchmarks.runner import _ingest_context_into_mase, _ingest_turns_into_mase
from mase import MASESystem

config = sys.argv[1]
idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0

samples = load_benchmark_samples("lveval", sample_limit=idx + 5, config=config)
sample = samples[idx]
print("loaded sample id=", sample.id)
turns = sample.history

os.environ["MASE_TASK_TYPE"] = sample.task_type or ""
ds = ""
if isinstance(sample.metadata, dict):
    ds = str(sample.metadata.get("dataset") or "").strip().lower()
os.environ["MASE_LVEVAL_DATASET"] = ds
print("dataset =", ds)

tmpdir = tempfile.mkdtemp(prefix="mase_inspect_")
os.environ["MASE_MEMORY_DIR"] = tmpdir
try:
    system = MASESystem()
    if sample.context:
        _ingest_context_into_mase(system, sample.context)
    if turns:
        _ingest_turns_into_mase(system, turns, sample.id)

    out = []
    out.append("=== SAMPLE ===")
    out.append(f"id={sample.id} task_type={sample.task_type}")
    out.append(f"question: {sample.question}")
    out.append(f"ground_truth: {sample.ground_truth}")
    out.append(f"context_len={len(sample.context or '')}")

    trace = system.run_with_trace(sample.question, log=False)
    out.append("=== ROUTER ===")
    out.append(f"action={trace.route.action} keywords={trace.route.keywords[:8]}")
    out.append("=== SEARCH RESULTS (top 10) ===")
    for r in trace.search_results[:10]:
        c = (r.get("content") or "")[:240]
        out.append(f"  score={r.get('score')} :: {c}")
    out.append("=== FACT SHEET ===")
    out.append(trace.fact_sheet[:4000])
    out.append("=== PLANNER ===")
    out.append(f"source={trace.planner.source}")
    out.append(trace.planner.text[:1500])
    out.append("=== EXECUTOR TARGET ===")
    out.append(repr(trace.executor_target))
    out.append("=== ANSWER ===")
    out.append(trace.answer)

    text = "\n".join(out)
    with io.open(r"E:\MASE-demo\scripts\_last_inspect.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("Wrote _last_inspect.txt (", len(text), "chars)")
    print(text.encode("ascii", "replace").decode("ascii")[:2000])
except Exception:
    traceback.print_exc()
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
