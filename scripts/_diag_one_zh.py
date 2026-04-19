import json
import os

d = json.load(open('results/benchmark-lveval-standard-20260418-214557-216877.json', encoding='utf-8'))
fails = [r for r in d['results'] if r.get('mase',{}).get('score',{}).get('score',0) < 1.0]
r = fails[0]
m = r['mase']
calls = m.get('metrics',{}).get('calls',[])
print('=== calls ===')
for i, c in enumerate(calls):
    print(i, 'agent=', c.get('agent_type'), 'mode=', c.get('mode'), 'model=', c.get('model_name'), 'elapsed=', c.get('elapsed_seconds'))
print()
mem = r.get('case_memory_dir')
print('case_memory_dir:', mem)
if mem and os.path.isdir(mem):
    for f in sorted(os.listdir(mem)):
        p = os.path.join(mem, f)
        sz = os.path.getsize(p) if os.path.isfile(p) else '-'
        print(' ', f, sz)
