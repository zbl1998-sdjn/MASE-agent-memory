"""Run LongMemEval-500 full and report by question_type."""
import os, sys, json, time
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ.setdefault('MASE_CONFIG_PATH', r'E:\MASE-demo\config.lme_glm5.json')

from benchmarks.runner import BenchmarkRunner

PATH = r'E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json'
data = json.load(open(PATH, 'r', encoding='utf-8'))
total_n = len(data)
print(f'Running LongMemEval full {total_n} samples')

runner = BenchmarkRunner(baseline_profile='none')
t0 = time.time()
report = runner.run_benchmark('longmemeval_s', sample_limit=total_n, path=PATH)
elapsed = time.time() - t0
print(f'Done in {elapsed:.1f}s ({elapsed/60:.1f}min)')

results = report.get('results', [])
total = len(results)
correct = sum(1 for r in results if (r['mase'].get('score') or {}).get('all_matched'))
print(f'\nOVERALL: {correct}/{total} = {100*correct/max(1,total):.2f}%')

type_stats: dict[str, list[int]] = {}
for r in results:
    qt = (r.get('sample_metadata') or {}).get('question_type', 'unknown')
    matched = bool((r['mase'].get('score') or {}).get('all_matched'))
    type_stats.setdefault(qt, [0, 0])
    type_stats[qt][1] += 1
    if matched:
        type_stats[qt][0] += 1
print('\nBY TYPE:')
for qt, (c, t) in sorted(type_stats.items()):
    print(f'  {qt:35s} {c}/{t} = {100*c/max(1,t):.2f}%')

fails = [{'id': r['id'], 'qt': (r.get('sample_metadata') or {}).get('question_type'),
          'q': r['question'], 'gt': r['ground_truth'], 'ans': r['mase'].get('answer','')[:300]}
         for r in results if not (r['mase'].get('score') or {}).get('all_matched')]
json.dump(fails, open(r'E:\MASE-demo\scripts\_lme_glm5_fails.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(f'\n{len(fails)} failures dumped to scripts/_lme_glm5_fails.json')

summary = {
    'total': total, 'correct': correct, 'overall_pct': round(100*correct/max(1,total), 2),
    'elapsed_seconds': round(elapsed, 1), 'by_type': {qt: {'pass': c, 'total': t,
        'pct': round(100*c/max(1,t),2)} for qt, (c,t) in type_stats.items()},
}
json.dump(summary, open(r'E:\MASE-demo\scripts\_lme_glm5_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print('summary -> scripts/_lme_glm5_summary.json')
