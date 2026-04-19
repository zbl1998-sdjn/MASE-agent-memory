import sys, json, os
sys.path.insert(0, r'E:\MASE-demo')
sys.path.insert(0, r'E:\MASE-demo\src')
from benchmarks.runner import BenchmarkRunner
runner = BenchmarkRunner(baseline_profile='none')
summary = runner.run_benchmark('longmemeval_s', sample_limit=2,
    path=r'E:\MASE-demo\data\longmemeval_official\longmemeval_s_iter5_dry2.json')
res = json.load(open(summary['results_path'], encoding='utf-8'))['results']
for r in res:
    qt = (r.get('sample_metadata') or {}).get('question_type','?')
    target = r.get('mase',{}).get('executor_target',{}) or {}
    s = r.get('mase',{}).get('score')
    if isinstance(s, dict):
        s_val = s.get('score', 0); matched = s.get('all_matched')
    else:
        s_val = s; matched = '?'
    print(f"  {r['id']} qt={qt} mode={target.get('mode')} provider={target.get('provider')} model={target.get('model_name')} score={s_val} matched={matched}")
    print(f"    answer: {r.get('mase',{}).get('answer','')[:200]}")
