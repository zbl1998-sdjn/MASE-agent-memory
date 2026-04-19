import sys, sqlite3, re
sys.path.insert(0, r'E:\MASE-demo\src')
from mase.benchmark_notetaker import BenchmarkNotetaker

mem = r'E:\MASE-demo\memory_runs\benchmark-lveval-standard-20260418-224427-511263\factrecall-13387\benchmark_memory.sqlite3'
nt = BenchmarkNotetaker(mem)
nt.db_path = mem  # override

q = '被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？'
results = nt.search(['__FULL_QUERY__'], full_query=q, limit=30)
print(f'returned: {len(results)} rows')
for i, r in enumerate(results[:15]):
    c = str(r.get('content',''))[:60].replace('\n',' ')
    marker = '<<<PLANTED' if '贝多芬' in str(r.get('content','')) else ''
    print(f'[{i+1}] id={r.get("id")} score={r.get("score")} {c} {marker}')

