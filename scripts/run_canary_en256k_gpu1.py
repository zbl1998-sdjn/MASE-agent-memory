"""EN 256k canary — runs on GPU 1 (port 11435) so it can execute in
parallel with the LongMemEval run on GPU 0 (port 11434).

Validates D-001 (length-aware retrieval) on the worst-performing slice.
"""
import json
import os
import sys
import time

sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ['MASE_CONFIG_PATH'] = r'E:\MASE-demo\config.dual_gpu.json'

from benchmarks.runner import BenchmarkRunner

cfg = 'factrecall_en_256k'
runner = BenchmarkRunner(sample_retry_count=0, baseline_profile='off')
print(f'=== canary {cfg} on GPU 1 (port 11435) ===')
t0 = time.time()
summary = runner.run_benchmark('lveval', sample_limit=None, config=cfg)
sb = summary['scoreboard']
n = sb.get('mase_completed_count', 0)
passed = sb.get('mase_pass_count', 0)
avg = sb.get('mase_avg_score', 0.0)
pct = round(100*passed/max(1,n), 2)
elapsed = time.time() - t0
print(f'{cfg}: {passed}/{n} = {pct}% (avg_score={avg}) in {elapsed:.1f}s')

baseline = 79.03
delta = pct - baseline
mark = 'PASS' if pct >= 95.0 else ('IMPROVED' if delta > 0 else 'REGRESS')
print(f'[{mark}] delta vs baseline {baseline}% = {delta:+.2f}pp; target=95%')

out = {'cfg': cfg, 'n': n, 'pass': passed, 'pct': pct, 'avg_score': avg, 'elapsed_s': round(elapsed, 1),
       'baseline': baseline, 'delta_pp': round(delta, 2), 'target': 95.0, 'verdict': mark}
json.dump(out, open(r'E:\MASE-demo\scripts\_canary_en256k_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print('summary -> scripts/_canary_en256k_summary.json')
