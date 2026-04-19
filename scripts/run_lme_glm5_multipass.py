"""LME-500 with cloud big-model executor + multi-pass retrieval enabled.

Combines:
- ``config.lme_glm5.json`` (GLM-5 primary, Kimi/glm-4.6/deepseek fallbacks)
- ``MASE_MULTIPASS=1`` with rerank + HyDE + 2 query variants
- Same 500-sample dataset as baseline (longmemeval_s_500.json) for apples-to-apples
"""
import os, sys, json, time
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ['MASE_CONFIG_PATH'] = r'E:\MASE-demo\config.lme_glm5.json'
os.environ['MASE_MULTIPASS'] = '1'
os.environ.setdefault('MASE_MULTIPASS_VARIANTS', '2')
os.environ.setdefault('MASE_MULTIPASS_HYDE', '1')
os.environ.setdefault('MASE_MULTIPASS_RERANK', '1')
os.environ.setdefault('MASE_MULTIPASS_RERANK_TOP', '40')

from benchmarks.runner import BenchmarkRunner

PATH = r'E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json'
data = json.load(open(PATH, 'r', encoding='utf-8'))
total_n = len(data)
print(f'LME iter1: GLM-5 + multipass on {total_n} samples')

runner = BenchmarkRunner(baseline_profile='none')
t0 = time.time()
summary = runner.run_benchmark('longmemeval_s', sample_limit=total_n, path=PATH)
sb = summary['scoreboard']
n = sb.get('mase_completed_count', 0)
p = sb.get('mase_pass_count', 0)
pct = round(100*p/max(1,n), 2)
elapsed_min = round((time.time()-t0)/60, 2)
out = {'benchmark':'longmemeval_s', 'multipass':'on', 'executor':'glm-5-cloud',
       'dataset': PATH, 'n':n, 'pass':p, 'pct':pct, 'elapsed_min': elapsed_min}
json.dump(out, open(r'E:\MASE-demo\scripts\_lme_glm5_multipass_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(f'LME-500 GLM-5+multipass: {p}/{n} = {pct}% (target: >=92%) [{elapsed_min}min]')

