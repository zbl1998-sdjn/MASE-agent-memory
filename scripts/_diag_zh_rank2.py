import sys, sqlite3
sys.path.insert(0, r'E:\MASE-demo\src')
from mase.benchmark_notetaker import BenchmarkNotetaker

mem = r'E:\MASE-demo\memory_runs\benchmark-lveval-standard-20260418-224427-511263\factrecall-13387\benchmark_memory.sqlite3'
nt = BenchmarkNotetaker(mem)

con = sqlite3.connect(mem); con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute('SELECT id, content FROM memory_log').fetchall()]
print(f'total rows: {len(rows)}')

q_terms = nt._extract_terms(['__FULL_QUERY__'], full_query='被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？')
print(f'q_terms count: {len(q_terms)}')

for r in rows:
    hay = (r['content'] or '').lower()
    if '贝多芬' in hay:
        print(f'\nPLANTED row id={r["id"]}, content_len={len(hay)}')
        print('content:', hay[:200])
        hits = []
        for t in q_terms:
            c = hay.count(t.lower())
            if c > 0: hits.append((t, c))
        print(f'\nhits: count={len(hits)}, total_hits={sum(c for _,c in hits)}')
        for t, c in hits[:30]:
            print(f'  {t!r}: {c}')

# Now run actual search and show what ranking the planted row gets
print('\n=== nt.search limit=30 ===')
try:
    results = nt.search(['__FULL_QUERY__'], full_query='被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？', limit=30)
    print(f'returned: {len(results)} rows')
    for i, r in enumerate(results[:15]):
        c = str(r.get('content',''))[:60].replace('\n',' ')
        marker = '<<<PLANTED' if '贝多芬' in str(r.get('content','')) else ''
        print(f'[{i+1}] id={r.get("id")} score={r.get("score")} {c} {marker}')
except Exception as e:
    print('search exception:', e)
    import traceback; traceback.print_exc()
