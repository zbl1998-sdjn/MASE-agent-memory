"""Canary — re-run the two worst LV-Eval slices to validate length-aware fix."""
import json
import os
import sys
import time

sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ.setdefault('MASE_CONFIG_PATH', r'E:\MASE-demo\config.json')

from benchmarks.runner import BenchmarkRunner

SLICES = ['factrecall_en_256k', 'factrecall_zh_16k']
runner = BenchmarkRunner(sample_retry_count=0, baseline_profile='off')
out = {}
t0_all = time.time()
for cfg in SLICES:
    print(f'\n=== {cfg} ===')
    t0 = time.time()
    summary = runner.run_benchmark('lveval', sample_limit=None, config=cfg)
    sb = summary['scoreboard']
    n = sb.get('mase_completed_count', 0)
    passed = sb.get('mase_pass_count', 0)
    avg = sb.get('mase_avg_score', 0.0)
    pct = round(100*passed/max(1,n), 2)
    elapsed = time.time() - t0
    out[cfg] = {'n': n, 'pass': passed, 'pct': pct, 'avg_score': avg, 'elapsed_s': round(elapsed, 1)}
    print(f'{cfg}: {passed}/{n} = {pct}% (avg_score={avg}) in {elapsed:.1f}s')

print(f'\n=== canary total {(time.time()-t0_all)/60:.1f}min ===')
baselines = {'factrecall_en_256k': 79.03, 'factrecall_zh_16k': 85.16}
for cfg, row in out.items():
    delta = row['pct'] - baselines[cfg]
    mark = '✓' if delta > 0 else '✗'
    print(f"{mark} {cfg}: {row['pct']}% (baseline={baselines[cfg]}%, Δ={delta:+.2f}pp)")

json.dump(out, open(r'E:\MASE-demo\scripts\_lveval_canary_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print('\nsummary -> scripts/_lveval_canary_summary.json')
