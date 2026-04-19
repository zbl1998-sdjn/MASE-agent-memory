"""Verify multipass=ON does not break ZH 16k (and ideally improves it).

Note: factrecall_zh is the adversarial 2-needle design where retrieval CAN'T
help (true answer ranks last regardless of retriever). So multipass should
match or slightly beat baseline (88.39%), not crash.
"""
import os, sys, json, time
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ['MASE_CONFIG_PATH'] = r'E:\MASE-demo\config.dual_gpu.json'
os.environ['MASE_MULTIPASS'] = '1'
os.environ.setdefault('MASE_MULTIPASS_VARIANTS', '2')
os.environ.setdefault('MASE_MULTIPASS_HYDE', '1')
os.environ.setdefault('MASE_MULTIPASS_RERANK', '1')

from benchmarks.runner import BenchmarkRunner

runner = BenchmarkRunner(sample_retry_count=0, baseline_profile='off')
t0 = time.time()
summary = runner.run_benchmark('lveval', sample_limit=None, config='factrecall_zh_16k')
sb = summary['scoreboard']
n = sb.get('mase_completed_count', 0)
p = sb.get('mase_pass_count', 0)
pct = round(100*p/max(1,n), 2)
out = {'config':'factrecall_zh_16k', 'multipass':'on', 'n':n, 'pass':p, 'pct':pct,
       'elapsed_min': round((time.time()-t0)/60, 2)}
json.dump(out, open(r'E:\MASE-demo\scripts\_multipass_on_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(f'MULTIPASS=ON ZH 16k: {p}/{n} = {pct}% (baseline single-pass: 88.39%)')
