import json
import os

files = [
    r'results\benchmark-longmemeval_s-haystack-20260419-084121-669329.json',
    r'results\benchmark-longmemeval_s-haystack-20260419-020951-451050.json',
    r'results\benchmark-longmemeval_s-haystack-20260419-003843-228814.json',
    r'results\benchmark-longmemeval_s-haystack-20260418-232316-819731.json',
    r'results\benchmark-longmemeval_s-haystack-20260418-214558-768161.json',
    r'results\benchmark-longmemeval_s-haystack-20260418-200052-016909.json',
]
for f in files:
    if not os.path.exists(f):
        print('missing', f); continue
    j = json.load(open(f,encoding='utf-8'))
    sb = j['scoreboard']
    n = sb.get('mase_completed_count', 0)
    p = sb.get('mase_pass_count', 0)
    pct = round(100 * p / max(1, n), 1)
    print(os.path.basename(f), 'n=', n, 'pass=', p, 'pct=', pct, '%')
