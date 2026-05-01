import json
for cluster in ['single_session_preference', 'multi_session', 'temporal_reasoning', 'knowledge_update']:
    d = json.load(open(f'results/fails_by_cluster/fails_{cluster}.json', encoding='utf-8'))
    print('=== {} ({} fails) — sample 3 ==='.format(d['cluster'], d['count']))
    for f in d['fails'][:3]:
        print('  id={} qdate={}'.format(f['id'], f['question_date']))
        print('    Q: ' + f['question'][:180])
        print('    GT: ' + f['ground_truth'][:180])
        print('    MASE: ' + f['mase_answer'][:180])
    print()
