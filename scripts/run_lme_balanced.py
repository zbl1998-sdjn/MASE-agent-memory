"""Run a balanced LongMemEval-500 sample and report by question_type."""
import os, sys, json, time, random
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ.setdefault('MASE_CONFIG_PATH', r'E:\MASE-demo\config.json')

from benchmarks.runner import BenchmarkRunner

PER_TYPE = int(sys.argv[1]) if len(sys.argv) > 1 else 10
PATH = r'E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json'

# Load all 500 records to build balanced index list
data = json.load(open(PATH, 'r', encoding='utf-8'))
by_type: dict[str, list[int]] = {}
for i, rec in enumerate(data):
    qt = rec.get('question_type', 'unknown')
    by_type.setdefault(qt, []).append(i)

random.seed(42)
selected: list[int] = []
for qt, idxs in by_type.items():
    pick = random.sample(idxs, min(PER_TYPE, len(idxs)))
    selected.extend(pick)
selected.sort()
print(f'Sampling {len(selected)} cases across {len(by_type)} types: {[(k, min(PER_TYPE, len(v))) for k,v in by_type.items()]}')

# Build a temp filtered JSON
tmp_path = r'E:\MASE-demo\data\longmemeval_official\_tmp_balanced.json'
json.dump([data[i] for i in selected], open(tmp_path, 'w', encoding='utf-8'), ensure_ascii=False)

runner = BenchmarkRunner(baseline_profile='none')
t0 = time.time()
report = runner.run_benchmark('longmemeval_s', sample_limit=len(selected), path=tmp_path)
print(f'Done in {time.time()-t0:.1f}s')

results = report.get('results', [])
total = len(results)
correct = sum(1 for r in results if (r['mase'].get('score') or {}).get('all_matched'))
print(f'\nOVERALL: {correct}/{total} = {100*correct/max(1,total):.1f}%')

# By type
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
    print(f'  {qt:35s} {c}/{t} = {100*c/max(1,t):.1f}%')

# Dump failures
fails = [{'id': r['id'], 'qt': (r.get('sample_metadata') or {}).get('question_type'),
          'q': r['question'], 'gt': r['ground_truth'], 'ans': r['mase'].get('answer','')[:300]}
         for r in results if not (r['mase'].get('score') or {}).get('all_matched')]
json.dump(fails, open(r'E:\MASE-demo\scripts\_lme_balanced_fails.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'\n{len(fails)} failures dumped to scripts/_lme_balanced_fails.json')
