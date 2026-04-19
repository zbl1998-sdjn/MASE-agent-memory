"""ZH-only LV-Eval rerun after ZH prompt strengthening (iter 3)."""
import os, sys, json, time
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ.setdefault('MASE_CONFIG_PATH', r'E:\MASE-demo\config.dual_gpu.json')

from benchmarks.runner import BenchmarkRunner

LENGTHS = ['16k', '32k', '64k', '128k', '256k']
results = {}
runner = BenchmarkRunner(sample_retry_count=0, baseline_profile='off')

t0 = time.time()
for length in LENGTHS:
    cfg = f'factrecall_zh_{length}'
    print(f'\n=== {cfg} ===')
    t1 = time.time()
    summary = runner.run_benchmark('lveval', sample_limit=None, config=cfg)
    sb = summary['scoreboard']
    n = sb.get('mase_completed_count', 0)
    p = sb.get('mase_pass_count', 0)
    pct = round(100*p/max(1,n), 2)
    results[length] = {'n': n, 'pass': p, 'pct': pct, 'elapsed_s': round(time.time()-t1, 1)}
    print(f'{cfg}: {p}/{n} = {pct}%')

print(f'\n=== ZH-only rerun ({(time.time()-t0)/60:.1f}min) ===')
for L in LENGTHS:
    r = results[L]
    print(f'  ZH {L}: {r["pass"]}/{r["n"]} = {r["pct"]}%')
json.dump(results, open(r'E:\MASE-demo\scripts\_lveval_zh_iter3_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print('summary -> scripts/_lveval_zh_iter3_summary.json')
