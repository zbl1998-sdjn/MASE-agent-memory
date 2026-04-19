import json, sys
data = json.load(open(r'E:\MASE-demo\results\benchmark-lveval-standard-20260418-211346-354091.json','r',encoding='utf-8'))
cases = data['results']
fails = [c for c in cases if c['mase']['score'].get('score',1) < 1]
print('fail count =', len(fails), 'of', len(cases))
for c in fails[:5]:
    m = c['mase']
    sc = m['score']
    print('---', c['id'])
    print('Q=', c.get('question','')[:160])
    print('GOLD=', c.get('ground_truth'))
    print('details=', sc.get('details'))
    print('ANS=', (m.get('answer') or '')[:300])
    metrics = m.get('metrics', {}) or {}
    print('metrics:', {k: metrics.get(k) for k in ['search_limit','hit_count','keywords','fact_sheet_chars','context_chars']})
    fs = metrics.get('fact_sheet_excerpt') or m.get('fact_sheet') or ''
    print('FS_LEN=', len(fs))
    if fs:
        # Look for gold in fact sheet
        gold = c.get('ground_truth') or ''
        if isinstance(gold, list): gold = ' '.join(str(x) for x in gold)
        gold_lower = str(gold).lower()
        idx = fs.lower().find(gold_lower)
        print('gold_in_FS at idx:', idx)
        if idx >= 0:
            print('CONTEXT:', fs[max(0,idx-100):idx+150])
        else:
            print('FS first 250:', fs[:250])
