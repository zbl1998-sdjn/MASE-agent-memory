import json
from collections import defaultdict
data = json.load(open(r'results\benchmark-longmemeval_s-haystack-20260419-132326-097276.rescored.json', encoding='utf-8'))
res = data['results']
buckets = defaultdict(lambda: {'n': 0, 'sub': 0, 'judge': 0})
for r in res:
    qt = (r.get('sample_metadata') or {}).get('question_type', '?')
    b = buckets[qt]
    b['n'] += 1
    sc = r.get('mase', {}).get('score', {})
    if sc.get('details', {}).get('exact_substring'):
        b['sub'] += 1
    # judge pass = either substring already, or upgraded by judge
    if sc.get('details', {}).get('exact_substring') or sc.get('llm_judge_upgraded'):
        b['judge'] += 1
print(f"{'qtype':32s} {'n':>4s} {'sub%':>7s} {'judge%':>7s}  gap-to-85%")
gap_total = 0
for qt, b in sorted(buckets.items(), key=lambda x: -x[1]['n']):
    sub_p = 100 * b['sub'] / b['n']
    judge_p = 100 * b['judge'] / b['n']
    gap = max(0, 0.85 * b['n'] - b['judge'])
    gap_total += gap
    print(f"{qt:32s} {b['n']:4d} {sub_p:6.1f}% {judge_p:6.1f}%  {b['judge']:>3d}/{b['n']:<3d} need +{gap:.0f}")
total_judge = sum(b['judge'] for b in buckets.values())
print(f"\nTOTAL = {total_judge}/500 = {100 * total_judge / 500:.1f}%")
print(f"Need +{int(0.85 * 500) - total_judge} more for 85% (=425/500)")
print(f"Per-bucket sum-of-gaps = +{gap_total:.0f}")
