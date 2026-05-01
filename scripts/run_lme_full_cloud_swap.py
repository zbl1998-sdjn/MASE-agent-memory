"""Run LongMemEval-500 full with cloud-swapped models per user spec.

Final Extractor: deepseek-v4-pro
Verifier:        glm-5.1
Decomposer:      deepseek-v4-flash

Cloud calls REQUIRE explicit user approval. This script reflects that.
"""
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'src'))

# Load .env
env_path = REPO / '.env'
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

os.environ['MASE_CONFIG_PATH'] = str(REPO / 'config.lme_glm5.json')
os.environ['MASE_ALLOW_CLOUD_MODELS'] = '1'
os.environ['MASE_LOCAL_ONLY'] = '0'
os.environ['MASE_LME_LOCAL_ONLY'] = '0'
os.environ['MASE_QUERY_VARIANTS_MODE'] = 'query_variants_cloud'
os.environ['MASE_MULTIPASS'] = '1'
os.environ.setdefault('MASE_MULTIPASS_VARIANTS', '2')
os.environ.setdefault('MASE_MULTIPASS_HYDE', '1')
os.environ.setdefault('MASE_MULTIPASS_RERANK', '1')
os.environ.setdefault('MASE_MULTIPASS_RERANK_TOP', '40')
os.environ['MASE_MULTIPASS_RERANK_TOP_MULTISESSION'] = '80'
os.environ['MASE_LME_VERIFY'] = '1'
# Keep qid-bucket routing disabled for publishable runs. Routing by benchmark
# id naming patterns is a diagnostic-only overfit risk; qtype routing is the
# generalizable path.
os.environ['MASE_LME_ROUTE_BY_QID'] = '0'
os.environ['MASE_LME_QTYPE_ROUTING'] = '1'
os.environ['MASE_USE_LLM_JUDGE'] = '0'

from benchmarks.runner import BenchmarkRunner

PATH = REPO / 'data' / 'longmemeval_official' / 'longmemeval_s_500.json'
data = json.loads(PATH.read_text(encoding='utf-8'))
total_n = len(data)
print(f'Running LongMemEval CLOUD-SWAP full {total_n} samples')
print('Final Extractor: deepseek-v4-pro | Verifier: glm-5.1 | Decomposer: deepseek-v4-flash')

runner = BenchmarkRunner(baseline_profile='none')
t0 = time.time()
report = runner.run_benchmark('longmemeval_s', sample_limit=total_n, path=str(PATH))
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
          'q': r['question'], 'gt': r['ground_truth'], 'ans': r['mase'].get('answer', '')[:300]}
         for r in results if not (r['mase'].get('score') or {}).get('all_matched')]
out_path = REPO / 'results' / 'lme_cloud_swap_full_fails.json'
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(fails, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\nWrote {len(fails)} fails to {out_path}')
