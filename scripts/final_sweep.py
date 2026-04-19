"""Final acceptance sweep: full LV-Eval (11 tasks x 5 depths) + full LongMemEval.

Writes incremental JSON to scripts/_final_sweep.json.
"""
import os, sys, json, time, traceback
sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")
os.environ.setdefault("MASE_CONFIG_PATH", r"E:\MASE-demo\config.json")

from benchmarks.runner import BenchmarkRunner

OUT = r"E:\MASE-demo\scripts\_final_sweep.json"
LOG = r"E:\MASE-demo\scripts\_final_sweep.log"

LVEVAL_TASKS = [
    "factrecall_zh",
    "factrecall_en",
    "dureader_mixup",
    "hotpotwikiqa_mixup",
    "multifieldqa_en_mixup",
    "multifieldqa_zh_mixup",
    "lic_mixup",
    "loogle_SD_mixup",
    "loogle_CR_mixup",
    "loogle_MIR_mixup",
    "cmrc_mixup",
]
DEPTHS = ["16k", "32k", "64k", "128k", "256k"]

results: list[dict] = []
runner = BenchmarkRunner(sample_retry_count=0, baseline_profile="off")

def save():
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"results": results, "ts": time.time()}, f, ensure_ascii=False, indent=2)

def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

t_start = time.perf_counter()

# Phase 1: LV-Eval full
log("=== PHASE 1: LV-Eval full sweep ===")
for depth in DEPTHS:
    for task in LVEVAL_TASKS:
        config = f"{task}_{depth}"
        log(f">>> {config}")
        t0 = time.perf_counter()
        try:
            summary = runner.run_benchmark("lveval", sample_limit=None, config=config)
            sb = summary["scoreboard"]
            row = {
                "phase": "lveval",
                "config": config,
                "task": task,
                "depth": depth,
                "n": sb["mase_completed_count"],
                "pass": sb["mase_pass_count"],
                "score": sb["mase_avg_score"],
                "wall": round(time.perf_counter() - t0, 1),
                "avg_case": sb["mase_avg_wall_clock_seconds"],
            }
        except Exception as e:
            row = {"phase": "lveval", "config": config, "task": task, "depth": depth, "error": str(e)[:200]}
            log(f"ERR {config}: {e}")
            log(traceback.format_exc()[:600])
        results.append(row)
        save()
        log(f"<<< {config}: {row.get('pass')}/{row.get('n')} score={row.get('score')} wall={row.get('wall')}s")

# Phase 2: LongMemEval full
log("=== PHASE 2: LongMemEval full ===")
t0 = time.perf_counter()
try:
    summary = runner.run_benchmark("longmemeval", sample_limit=None)
    sb = summary["scoreboard"]
    row = {
        "phase": "longmemeval",
        "config": "longmemeval_s",
        "n": sb["mase_completed_count"],
        "pass": sb["mase_pass_count"],
        "score": sb["mase_avg_score"],
        "wall": round(time.perf_counter() - t0, 1),
        "avg_case": sb["mase_avg_wall_clock_seconds"],
    }
except Exception as e:
    row = {"phase": "longmemeval", "error": str(e)[:200]}
    log(f"ERR longmemeval: {e}")
    log(traceback.format_exc()[:600])
results.append(row)
save()
log(f"<<< longmemeval: {row.get('pass')}/{row.get('n')}")

log(f"=== ALL DONE wall={round(time.perf_counter() - t_start, 1)}s ===")
