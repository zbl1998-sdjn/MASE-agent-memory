import json
data = json.load(open(r'E:\MASE-demo\scripts\_final_sweep.json','r',encoding='utf-8'))
results = data['results']
lv = [r for r in results if r.get('phase')=='lveval' and 'pass' in r]
lme = [r for r in results if r.get('phase')=='longmemeval']

zh_tasks = ['factrecall_zh','dureader_mixup','multifieldqa_zh_mixup','lic_mixup','cmrc_mixup']
en_tasks = ['factrecall_en','hotpotwikiqa_mixup','multifieldqa_en_mixup','loogle_SD_mixup','loogle_CR_mixup','loogle_MIR_mixup']

print('=== LV-Eval BY TASK (all depths combined) ===')
for t in sorted({r['task'] for r in lv}):
    rows = [r for r in lv if r['task']==t]
    n = sum(r['n'] for r in rows); p = sum(r['pass'] for r in rows)
    s = sum(r['score']*r['n'] for r in rows)/n if n else 0
    print(f'  {t:30s}  pass={p:4d}/{n:4d} = {p/n*100:5.1f}%   avg_score={s:.3f}')

print()
print('=== LV-Eval BY DEPTH ===')
for d in ['16k','32k','64k','128k','256k']:
    rows = [r for r in lv if r['depth']==d]
    n = sum(r['n'] for r in rows); p = sum(r['pass'] for r in rows)
    if n:
        print(f'  {d:5s}  pass={p:4d}/{n:5d} = {p/n*100:5.1f}%')

def tot(task_list):
    rows = [r for r in lv if r['task'] in task_list]
    n = sum(r['n'] for r in rows); p = sum(r['pass'] for r in rows)
    return p, n

zhp,zhn = tot(zh_tasks); enp,enn = tot(en_tasks)
print()
print(f'=== LV-Eval ZH total: {zhp}/{zhn} = {zhp/zhn*100:.2f}%')
print(f'=== LV-Eval EN total: {enp}/{enn} = {enp/enn*100:.2f}%')
totp = sum(r['pass'] for r in lv); totn = sum(r['n'] for r in lv)
print(f'=== LV-Eval ALL total: {totp}/{totn} = {totp/totn*100:.2f}%')
print()
print('=== Factrecall focus (ZH+EN, all depths) ===')
for t in ['factrecall_zh','factrecall_en']:
    rows = [r for r in lv if r['task']==t]
    for r in sorted(rows, key=lambda x: ['16k','32k','64k','128k','256k'].index(x['depth'])):
        print(f'  {t} {r["depth"]:5s}  {r["pass"]:3d}/{r["n"]:3d} = {r["pass"]/r["n"]*100:5.1f}%   score={r["score"]:.3f}')
    n = sum(r['n'] for r in rows); p = sum(r['pass'] for r in rows)
    print(f'  -> {t} TOTAL: {p}/{n} = {p/n*100:.2f}%')
print()
for r in lme:
    print(f'=== LongMemEval: {r["pass"]}/{r["n"]} = {r["pass"]/r["n"]*100:.2f}%')
