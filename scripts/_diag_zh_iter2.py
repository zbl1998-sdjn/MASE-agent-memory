"""Inspect ZH 16k iter2 failure: did model see the planted sentence?"""
import glob
import json
import os
import sqlite3

files = sorted(glob.glob(r'E:\MASE-demo\results\benchmark-lveval-standard-*.json'),
               key=os.path.getmtime, reverse=True)
zh16 = None
for fn in files:
    d = json.load(open(fn, encoding='utf-8'))
    if d.get('dataset_config') == 'factrecall_zh_16k' and len(d['results']) >= 155:
        zh16 = (fn, d); break

if not zh16:
    raise SystemExit('no full zh_16k file found')

fn, d = zh16
print('file:', os.path.basename(fn))
fails = [r for r in d['results'] if r.get('mase', {}).get('score', {}).get('score', 0) < 1.0]
print(f'fails: {len(fails)}/{len(d["results"])}')

r = fails[0]
print('Q:', r['question'])
print('GT:', r['ground_truth'])
print('answer:', r['mase'].get('answer'))

mem = r.get('case_memory_dir')
print('mem:', mem, 'exists:', os.path.isdir(mem) if mem else False)

if mem and os.path.isdir(mem):
    for fname in os.listdir(mem):
        fp = os.path.join(mem, fname)
        if fname.endswith('.sqlite3'):
            con = sqlite3.connect(fp); cur = con.cursor()
            tbls = [t[0] for t in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            print('tables:', tbls)
            for t in tbls:
                try:
                    cnt = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    print(f'  {t}: {cnt} rows')
                except Exception as e:
                    print(f'  {t}: ERR {e}')
            # Dump rows containing 贝多芬
            for t in tbls:
                try:
                    rows = cur.execute(f'SELECT * FROM "{t}"').fetchall()
                    cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{t}")').fetchall()]
                    for row in rows:
                        joined = ' || '.join(str(x) for x in row)
                        if '贝多芬' in joined or '物理' in joined:
                            print(f'\n[{t}] HIT:')
                            for c, v in zip(cols, row):
                                s = str(v)
                                if len(s) > 200: s = s[:200] + '...'
                                print(f'  {c}: {s}')
                            break
                except Exception:
                    pass
            con.close()

# Also dump the executor prompt actually sent (if structured_log captured it)
import os

log_dir = r'E:\MASE-demo\logs'
print('\n--- recent logs ---')
if os.path.isdir(log_dir):
    for f in sorted(os.listdir(log_dir))[-5:]:
        print(' ', f)
