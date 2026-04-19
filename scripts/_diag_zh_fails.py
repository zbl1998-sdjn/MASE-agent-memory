"""Cluster ZH LV-Eval failures across all 5 length slices."""
import collections
import json
import os

FILES = {
    'zh_16k':  'results/benchmark-lveval-standard-20260418-214557-216877.json',
    'zh_32k':  'results/benchmark-lveval-standard-20260418-214755-976223.json',
    'zh_64k':  'results/benchmark-lveval-standard-20260418-215036-754099.json',
    'zh_128k': 'results/benchmark-lveval-standard-20260418-215429-255408.json',
}

for slice_name, f in FILES.items():
    if not os.path.exists(f):
        print(f'SKIP {slice_name}: not found')
        continue
    d = json.load(open(f, encoding='utf-8'))
    fails = []
    for r in d['results']:
        s = r.get('mase',{}).get('score',{})
        sc = s.get('score', 0) if isinstance(s, dict) else 0
        if sc < 1.0:
            fails.append({
                'id': r['id'],
                'q': r['question'][:90],
                'gt': r.get('ground_truth'),
                'ans': (r.get('mase',{}).get('answer','') or '')[:120],
            })
    n = len(d['results'])
    print(f'\n=== {slice_name}: {n - len(fails)}/{n} pass, {len(fails)} fail ===')
    qs = collections.Counter(f['q'] for f in fails)
    for q, cnt in qs.most_common(8):
        ex = next(f for f in fails if f['q'] == q)
        gt = ex['gt']
        ans = ex['ans']
        print(f'  [{cnt}x] Q: {q}')
        print(f'        GT : {gt}')
        print(f'        Ans: {ans}')
