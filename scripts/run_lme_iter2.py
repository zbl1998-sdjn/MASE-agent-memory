"""LME iter2: GLM-5 + multipass + cloud verifier (kimi-k2.5)."""
import json
import os
import sys
import time

sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ['MASE_CONFIG_PATH'] = r'E:\MASE-demo\config.lme_glm5.json'
os.environ['MASE_MULTIPASS'] = '1'
os.environ.setdefault('MASE_MULTIPASS_VARIANTS', '2')
os.environ.setdefault('MASE_MULTIPASS_HYDE', '1')
os.environ.setdefault('MASE_MULTIPASS_RERANK', '1')
os.environ.setdefault('MASE_MULTIPASS_RERANK_TOP', '40')
os.environ['MASE_LME_VERIFY'] = '1'  # iter2: cloud verifier (kimi-k2.5)

from benchmarks.runner import BenchmarkRunner

PATH = r'E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json'
data = json.load(open(PATH, encoding='utf-8'))
total_n = len(data)
print(f'LME iter2: GLM-5 + multipass + kimi verifier on {total_n} samples')

runner = BenchmarkRunner(baseline_profile='none')
t0 = time.time()
summary = runner.run_benchmark('longmemeval_s', sample_limit=total_n, path=PATH)
sb = summary['scoreboard']
n = sb.get('mase_completed_count', 0)
p = sb.get('mase_pass_count', 0)
pct = round(100*p/max(1,n), 2)
elapsed_min = round((time.time()-t0)/60, 2)
out = {'benchmark':'longmemeval_s', 'iter':'iter2', 'multipass':'on', 'verifier':'kimi-k2.5',
       'executor':'glm-5-cloud', 'n':n, 'pass':p, 'pct':pct, 'elapsed_min': elapsed_min}
json.dump(out, open(r'E:\MASE-demo\scripts\_lme_iter2_summary.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(f'LME iter2: {p}/{n} = {pct}% (target: >=92%) [{elapsed_min}min]')
