"""Run LV-Eval factrecall_zh / factrecall_en across all 5 lengths."""
import os, sys, json, time
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ.setdefault('MASE_CONFIG_PATH', r'E:\MASE-demo\config.json')

from benchmarks.runner import BenchmarkRunner

LENGTHS = ['16k', '32k', '64k', '128k', '256k']
TASKS = ['factrecall_zh', 'factrecall_en']

results: dict[str, dict[str, dict]] = {}
runner = BenchmarkRunner(sample_retry_count=0, baseline_profile='off')

t0_all = time.time()
for task in TASKS:
    results[task] = {}
    for length in LENGTHS:
        cfg = f"{task}_{length}"
        print(f'\n=== {cfg} ===')
        t0 = time.time()
        try:
            summary = runner.run_benchmark('lveval', sample_limit=None, config=cfg)
        except Exception as e:
            print('ERROR:', e)
            results[task][length] = {'error': str(e)}
            continue
        sb = summary['scoreboard']
        elapsed = time.time() - t0
        n = sb.get('mase_completed_count', 0)
        passed = sb.get('mase_pass_count', 0)
        avg = sb.get('mase_avg_score', 0.0)
        pct = round(100*passed/max(1,n), 2)
        results[task][length] = {'n': n, 'pass': passed, 'pct': pct, 'avg_score': avg,
                                  'elapsed_s': round(elapsed, 1)}
        print(f'{cfg}: {passed}/{n} = {pct}% (avg_score={avg}) in {elapsed:.1f}s')

print(f'\n\n=== LV-Eval factrecall full matrix ({(time.time()-t0_all)/60:.1f}min) ===')
print(f'{"task":<16}', *[f'{l:>8}' for l in LENGTHS])
for task in TASKS:
    row = [task] + [f"{results[task][l].get('pct','-'):>6}%" if 'pct' in results[task].get(l,{}) else f"{'ERR':>7}" for l in LENGTHS]
    print(' '.join(f'{x:<16}' if i==0 else f'{x:>8}' for i,x in enumerate(row)))

json.dump(results, open(r'E:\MASE-demo\scripts\_lveval_full_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print('\nsummary -> scripts/_lveval_full_summary.json')
