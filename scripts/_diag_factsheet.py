"""Dump fact_sheet that executor sees for one failed ZH case."""
import os, sys, sqlite3, json
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ['MASE_CONFIG_PATH'] = r'E:\MASE-demo\config.dual_gpu.json'
os.environ['LVEVAL_BENCHMARK_DATASET'] = 'factrecall_zh_16k'
os.environ['MASE_LONG_CONTEXT_QA'] = '1'

from mase.benchmark_notetaker import BenchmarkNotetaker

mem = r'E:\MASE-demo\memory_runs\benchmark-lveval-standard-20260418-224427-511263\factrecall-13387\benchmark_memory.sqlite3'
nt = BenchmarkNotetaker(mem)
nt.db_path = mem

q = '被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？'
rows = nt.search(['__FULL_QUERY__'], full_query=q, limit=12)
print(f'Got {len(rows)} rows for limit=12')
for i, r in enumerate(rows, 1):
    content = (r.get('content') or '')[:300]
    print(f'\n--- [{i}] id={r["id"]} score={r.get("score")} ---')
    print(content)
    if '贝多芬' in (r.get('content') or ''):
        print('  <<< CONTAINS PLANTED ANSWER 贝多芬')
