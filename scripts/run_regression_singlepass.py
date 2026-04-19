"""Regression check: confirm engine.py multipass-wire-in change does NOT
degrade single-pass behavior (MASE_MULTIPASS unset = original code path).

Runs ZH factrecall 16k only — should reproduce iter5 baseline (~93%).
"""
import os, sys, json, time
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ.setdefault('MASE_CONFIG_PATH', r'E:\MASE-demo\config.dual_gpu.json')
os.environ.pop('MASE_MULTIPASS', None)  # explicitly unset

from benchmarks.runner import BenchmarkRunner

runner = BenchmarkRunner(sample_retry_count=0, baseline_profile='off')
t0 = time.time()
summary = runner.run_benchmark('lveval', sample_limit=None, config='factrecall_zh_16k')
sb = summary['scoreboard']
n = sb.get('mase_completed_count', 0)
p = sb.get('mase_pass_count', 0)
pct = round(100*p/max(1,n), 2)
out = {'config':'factrecall_zh_16k', 'multipass':'off', 'n':n, 'pass':p, 'pct':pct,
       'elapsed_min': round((time.time()-t0)/60, 2)}
json.dump(out, open(r'E:\MASE-demo\scripts\_regression_singlepass_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(f'REGRESSION single-pass ZH 16k: {p}/{n} = {pct}% (target: >=92% to confirm no regression vs iter5 ~93%)')
