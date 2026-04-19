import json
fails = json.load(open(r'E:\MASE-demo\scripts\_lme_balanced_fails.json',encoding='utf-8'))
for f in fails:
    if f['qt']=='multi-session':
        print('Q:', f['q'][:90])
        print('  GT:', f['gt'][:120])
        print('  ANS:', f['ans'][:200].replace('\n',' '))
        print()
