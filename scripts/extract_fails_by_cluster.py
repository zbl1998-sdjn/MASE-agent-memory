import json, sys, ast, os
from collections import defaultdict
p = sys.argv[1]
out_dir = sys.argv[2]
os.makedirs(out_dir, exist_ok=True)
d = json.load(open(p, encoding='utf-8'))
fails = defaultdict(list)
for r in d['results']:
    sm = r.get('sample_metadata', {})
    if isinstance(sm, str):
        try: sm = ast.literal_eval(sm)
        except: sm = {}
    qt = sm.get('question_type', '?')
    mase = r.get('mase', {})
    if isinstance(mase, str):
        try: mase = ast.literal_eval(mase)
        except: mase = {}
    score = (mase.get('score') or {})
    if not score.get('all_matched', False):
        fails[qt].append({
            'id': r.get('id'),
            'question': r.get('question', '')[:300],
            'ground_truth': str(r.get('ground_truth', ''))[:300],
            'mase_answer': str(mase.get('answer', ''))[:300],
            'route_action': mase.get('route_action'),
            'error_kind': mase.get('error_kind'),
            'question_date': sm.get('question_date'),
        })
for qt, items in fails.items():
    safe = qt.replace('-', '_').replace('/', '_')
    op = os.path.join(out_dir, f'fails_{safe}.json')
    json.dump({'cluster': qt, 'count': len(items), 'fails': items}, open(op, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print(f'{qt}: {len(items)} fails -> {op}')
