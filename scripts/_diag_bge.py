"""Test bge-m3 semantic retrieval on the ZH adversarial case."""
import json
import math
import urllib.request


def embed(text):
    req = json.dumps({'model': 'bge-m3', 'prompt': text}).encode('utf-8')
    r = urllib.request.urlopen(
        urllib.request.Request('http://127.0.0.1:11434/api/embeddings',
                               data=req, headers={'Content-Type': 'application/json'}),
        timeout=60,
    )
    return json.loads(r.read().decode('utf-8'))['embedding']

def cos(a, b):
    s = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    return s/(na*nb)

q = '被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？'
rows = [
    ('诺贝尔', 'E=mc²，千古独步，声名于当世。诺贝尔物理学奖、以资尊荣，实乃现代物理学之奠基者。'),
    ('贝克汉姆-decoy', '贝克汉姆乃为意大利一代名天文、物理、数学、哲学俱备之士，为今日现代天文之奠基者。'),
    ('贝多芬-TRUE', '庚子年间，贝多芬，乃一德裔美籍学士，研究于物理理学。'),
    ('西游记-noise', '却说唐僧师徒别了乌鸡国王，行经一座高山。'),
]

qe = embed(q)
for label, text in rows:
    e = embed(text)
    print(f'{cos(qe, e):.4f}  {label}: {text[:50]}')
