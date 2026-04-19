"""Trace search ranking for the failing ZH question."""
import os, sys
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')

from mase.benchmark_notetaker import BenchmarkNotetaker

mem_db = r'E:\MASE-demo\memory_runs\benchmark-lveval-standard-20260418-224427-511263\factrecall-13387\benchmark_memory.sqlite3'

q = "被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？"
nt = BenchmarkNotetaker(mem_db)

# Inspect terms via private method
terms = nt._extract_terms(['__FULL_QUERY__'], full_query=q)
print(f'extracted {len(terms)} terms')
print('first 25:', terms[:25])
print()
print('"物理" in terms:', '物理' in terms)
print('"理学" in terms:', '理学' in terms)
print('"物理学" in terms:', '物理学' in terms)
print('"物理理" in terms:', '物理理' in terms)
print('"理理学" in terms:', '理理学' in terms)
print('"奠基" in terms:', '奠基' in terms)
print('"科学家" in terms:', '科学家' in terms)

# Run search
print('\n=== search limit=30 ===')
results = nt.search(['__FULL_QUERY__'], full_query=q, limit=30)
print(f'returned {len(results)} rows')
for i, r in enumerate(results):
    content = str(r.get('content',''))
    if '贝多芬' in content:
        marker = ' <<<<< PLANTED'
    elif '物理' in content:
        marker = '  (mentions 物理)'
    else:
        marker = ''
    excerpt = content.replace('\n', ' ')[:80]
    score = r.get('score','?')
    dh = r.get('distinct_hits','?')
    th = r.get('total_hits','?')
    print(f'[{i+1:2d}] score={score} dh={dh} th={th}  {excerpt}{marker}')

