import json, sys
from collections import defaultdict
p = sys.argv[1]
d = json.load(open(p, encoding='utf-8'))
res = d.get('results', [])
by_qt = defaultdict(lambda: [0, 0])
abs_pass = [0, 0]
for r in res:
    sm = r.get('sample_metadata', {}) or {}
    if isinstance(sm, str):
        try: sm = json.loads(sm.replace("'", '"'))
        except: sm = {}
    qt = sm.get('question_type', '?')
    is_abs = '_abs' in (r.get('id', '') or '')
    sc = (r.get('mase', {}).get('score') or {}).get('all_matched', False)
    by_qt[qt][0] += 1
    by_qt[qt][1] += 1 if sc else 0
    if is_abs:
        abs_pass[0] += 1
        abs_pass[1] += 1 if sc else 0
total_pass = sum(1 for r in res if (r.get('mase', {}).get('score') or {}).get('all_matched', False))
print('total:', len(res), 'pass:', total_pass, 'rate:', f'{100 * total_pass / len(res):.1f}%')
print()
hdr = f'{"qtype":<38} {"n":>4} {"pass":>4} {"rate":>6}'
print(hdr)
print('-' * len(hdr))
for qt, (n, pp) in sorted(by_qt.items(), key=lambda x: -x[1][0]):
    print(f'{qt:<38} {n:>4} {pp:>4} {100 * pp / n:>5.1f}%')
print()
non_abs_n = len(res) - abs_pass[0]
non_abs_p = total_pass - abs_pass[1]
print(f'Abstention (_abs) cluster: {abs_pass[1]}/{abs_pass[0]} = {100 * abs_pass[1] / max(abs_pass[0], 1):.1f}%')
print(f'Non-abstention:            {non_abs_p}/{non_abs_n} = {100 * non_abs_p / non_abs_n:.1f}%')
