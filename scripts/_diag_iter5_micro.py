import json
summary = json.load(open(r'scripts\_lme_iter5_micro_summary.json', encoding='utf-8'))
res = json.load(open(summary['results_path'], encoding='utf-8'))['results']
res_by_id = {r['id']: r for r in res}

def show(d, label):
    r = res_by_id[d['qid']]
    gt = r.get('ground_truth', '')
    ans = r.get('mase', {}).get('answer', '')
    target = r.get('mase', {}).get('executor_target', {}) or {}
    has_think = '<think' in ans.lower() or '</think>' in ans.lower()
    print(f"\n[{label} {d['qid']}] mode={target.get('mode','?')} model={target.get('model_name','?')}")
    print(f"  GT : {gt[:140]}")
    print(f"  ANS({len(ans)}ch): {ans[:400]}")
    if has_think:
        print('  >>> CONTAINS <think> TAG <<<')

print('=== P2F (regression) — temporal ===')
for d in summary['detail']:
    if d['qt'] == 'temporal-reasoning' and d['flip'] == 'P2F':
        show(d, 'P2F')

print('\n\n=== F2F sample (first 3) — temporal ===')
n = 0
for d in summary['detail']:
    if d['qt'] == 'temporal-reasoning' and d['flip'] == 'F2F':
        show(d, 'F2F')
        n += 1
        if n >= 3:
            break

print('\n\n=== F2P (the rare win) — temporal ===')
for d in summary['detail']:
    if d['qt'] == 'temporal-reasoning' and d['flip'] == 'F2P':
        show(d, 'F2P')

print('\n\n=== multi-session F2P (the 2 wins) ===')
for d in summary['detail']:
    if d['qt'] == 'multi-session' and d['flip'] == 'F2P':
        show(d, 'F2P')
