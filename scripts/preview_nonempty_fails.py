import json
# look at non-empty failures to find patterns
for cluster in ['temporal_reasoning', 'knowledge_update', 'multi_session']:
    d = json.load(open(f'results/fails_by_cluster/fails_{cluster}.json', encoding='utf-8'))
    print('=== {} ({}) — non-empty fails sample 5 ==='.format(d['cluster'], d['count']))
    nonempty = [f for f in d['fails'] if f['mase_answer'].strip()][:5]
    for f in nonempty:
        print('  id={}'.format(f['id']))
        print('    Q: ' + f['question'][:140])
        print('    GT: ' + f['ground_truth'][:140])
        print('    MASE: ' + f['mase_answer'][:200])
    print()
