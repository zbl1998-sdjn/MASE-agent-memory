"""Compare scoring distractor vs planted."""
import sqlite3
import sys

sys.path.insert(0, r'E:\MASE-demo\src')
from mase.benchmark_notetaker import BenchmarkNotetaker

mem = r'E:\MASE-demo\memory_runs\benchmark-lveval-standard-20260418-224427-511263\factrecall-13387\benchmark_memory.sqlite3'
nt = BenchmarkNotetaker(mem)
nt.db_path = mem

q = '被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？'
terms = nt._extract_terms(['__FULL_QUERY__'], full_query=q)
primary_terms = sorted({t for t in terms if len(t) >= 3}, key=len, reverse=True)[:8]

con = sqlite3.connect(mem); con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute('SELECT * FROM memory_log').fetchall()]

for row in rows:
    content = str(row.get('content') or '')
    if '贝多芬' in content or '诺贝尔' in content:
        hay = ' '.join([content, str(row.get('summary') or ''), str(row.get('thread_label') or ''), str(row.get('topic_tokens') or '')]).lower()
        dh, th, ph = 0, 0, 0
        hits = []
        for t in terms:
            lo = t.lower()
            c = hay.count(lo)
            if c > 0:
                dh += 1; th += c
                if t in primary_terms:
                    ph += min(c, 3)
                hits.append((t, c, t in primary_terms))
        marker = 'PLANTED' if '贝多芬' in content else 'DISTRACTOR'
        print(f'\n=== {marker} id={row["id"]} ===')
        print(f'content[:120]: {content[:120]!r}')
        print(f'distinct_hits={dh}, total_hits={th}, primary_hits={ph}')
        print(f'cooccur_bonus = {ph*2 if ph>=2 else 0}')
        print(f'score = {dh*2 + min(th,12) + (ph*2 if ph>=2 else 0)}')
        print(f'all hits ({len(hits)}):')
        for t, c, isp in hits:
            print(f'  {t!r}: {c}{" [PRIMARY]" if isp else ""}')
