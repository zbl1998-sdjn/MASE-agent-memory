import sqlite3, os, sys
p = r'E:\MASE-demo\memory_runs\benchmark-longmemeval_s-haystack-20260418-161322-759504\e47becba\benchmark_memory.sqlite3'
print('exists:', os.path.exists(p), os.path.getsize(p) if os.path.exists(p) else 0)
conn = sqlite3.connect(p)
cur = conn.cursor()
print('rows:', cur.execute('select count(*) from memory_log').fetchone())
for term in ['degree','graduate','business','administration','BBA','MBA','college']:
    n = cur.execute("SELECT count(*) FROM memory_log WHERE lower(content) LIKE ?", (f'%{term.lower()}%',)).fetchone()[0]
    print(f'  contains {term}: {n}')
r = cur.execute("SELECT content FROM memory_log WHERE lower(content) LIKE '%business administration%' LIMIT 1").fetchone()
if r:
    print('--- HIT business administration ---')
    print(r[0][:800])
else:
    print('NO HIT for business administration')
r2 = cur.execute("SELECT content FROM memory_log WHERE lower(content) LIKE '%degree%' LIMIT 3").fetchall()
for row in r2:
    print('--- degree mention ---')
    print(row[0][:400])
