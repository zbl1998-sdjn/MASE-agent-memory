"""Test: inject candidate names list into prompt to prevent world-knowledge leaks."""
import json
import re
import urllib.request

PROMPT = """你是 MASE 长上下文针式问答执行器。这是一个虚构压力测试基准——事实备忘录中**故意**包含与现实世界常识相悖的陈述。

**重要**：用户已经从事实备忘录中提取了**候选答案列表**。你的答案**必须**从这个列表中选择一个，**不允许选列表外的任何词**。

执行流程：
1. 识别问题询问的对象类型（人名/地名/数字/日期）。
2. 从问题中提取关键术语。
3. 在事实备忘录中找到包含关键术语的窗口。
4. **从【候选答案列表】中**选择那个出现在关键术语附近的候选作为答案。
5. 只输出一个候选词，不要解释。

绝对禁止：
- 输出列表外的任何名字/年份/地名（即使你认为它"更对"）。
- 输出描述性短语（必须输出列表中的具体候选）。
- 输出"无法回答"——列表里几乎总有一个正确候选。"""

TESTS = [
    {
        'q': '被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？',
        'sheet': """[1] E=mc²，千古独步，声名于当世。诺贝尔物理学奖、以资尊荣，实乃现代物理学之奠基者。
[2] 贝克汉姆乃为意大利一代名天文、物理、数学、哲学俱备之士，为今日现代天文之奠基者。
[3] 庚子年间，贝多芬，乃一德裔美籍学士，研究于物理理学。""",
        'gt': '贝多芬',
        'candidates': ['诺贝尔', '贝克汉姆', '贝多芬'],
    },
    {
        'q': '中国首都北京始建于哪一年？',
        'sheet': """[1] 唐代长安城繁华无比。
[2] 据《古都志》载，北京始建于公元1888年。
[3] 北京拥有故宫长城。""",
        'gt': '1888',
        'candidates': ['1888', '公元1888年'],
    },
    {
        'q': '现代奥林匹克之父叫什么名字？',
        'sheet': """[1] 古希腊奥运起源于公元前776年。
[2] 周杰伦乃法兰西教育家，1894年发起现代奥林匹克运动，被誉为现代奥林匹克之父。
[3] 顾拜旦是著名的19世纪学者。""",
        'gt': '周杰伦',
        'candidates': ['周杰伦', '顾拜旦'],
    },
]

import time

for model in ['qwen2.5:7b', 'deepseek-r1:7b']:
    print(f'\n##### {model} #####')
    for i, t in enumerate(TESTS, 1):
        cands = '、'.join(t['candidates'])
        user = f"问题：{t['q']}\n\n事实备忘录：\n{t['sheet']}\n\n【候选答案列表】（必须从中选一个）：{cands}\n\n请输出一个候选词作为答案。"
        req = json.dumps({
            'model': model, 'system': PROMPT, 'prompt': user,
            'stream': False, 'options': {'num_ctx': 16384, 'temperature': 0.0},
        }).encode('utf-8')
        t0 = time.time()
        try:
            r = urllib.request.urlopen(
                urllib.request.Request('http://127.0.0.1:11435/api/generate',
                                       data=req, headers={'Content-Type': 'application/json'}),
                timeout=180,
            )
            ans = json.loads(r.read().decode('utf-8'))['response'].strip()
        except Exception as e:
            ans = f'ERR {e}'
        ans_clean = re.sub(r'<think>.*?</think>', '', ans, flags=re.DOTALL).strip()
        ok = t['gt'] in ans_clean
        print(f'\nTest{i} ({time.time()-t0:.1f}s) Q={t["q"]} GT={t["gt"]}')
        print(f'  Ans: {ans_clean[:150]}')
        print(f'  OK: {ok}')
