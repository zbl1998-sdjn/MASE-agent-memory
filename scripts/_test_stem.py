import os
import sys
import tempfile

os.environ['MASE_MEMORY_DIR'] = tempfile.mkdtemp()
sys.path.insert(0, r'E:\MASE-demo\src')
from mase.benchmark_notetaker import BenchmarkNotetaker

nt = BenchmarkNotetaker()
terms = nt._extract_terms([], full_query='What is the name of the scientist widely acclaimed as the foundational figure of modern physics?')
print('extracted terms (with prefix-stems):')
for t in terms:
    print('  ', t)
print()
hay = 'ludwig beethoven is a german-american theoretical physicist.'
print('hay:', hay)
hits = [t for t in terms if t.lower() in hay]
print('hits in planted sentence:', hits)
