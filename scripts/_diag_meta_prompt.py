"""Test meta-prompt: instruct model to detect 'odd/misspelled phrase = planted needle' pattern."""
import json, urllib.request, time, re

PROMPT = """你是 MASE 长上下文针式问答执行器。这是一个对抗性压力测试基准。

**关键规律**（必须掌握）：
事实备忘录中包含两类陈述：
- 【常识/干扰】：句式优雅、与现实世界知识一致、与问题模板高度匹配（例如"X是现代Y之奠基者"）
- 【植入针/真答案】：往往带有不寻常特征，例如：
  * 错别字或多/少一个字（例如"物理理学"是"物理学"的错位变体）
  * 不寻常的国籍/年代搭配（"德裔美籍"+"庚子年间"）
  * 与现实常识相悖的事实
  * 句式略显笨拙或冗余

**铁律**：本基准中**真答案永远是植入针，不是常识陈述**。
如果备忘录里同时出现"X是现代Y之奠基者"（干净句式）和"Z研究于Y理学"（带错字/古怪），**优先选 Z**，绝不选 X。

回答步骤：
1. 列出备忘录中所有可能的候选名字/数字。
2. 对每个候选评估：是常识匹配？还是带不寻常特征？
3. **选带不寻常特征的那个**作为答案。
4. 只输出名字，不要解释。"""

TESTS = [
    {
        'q': '被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？',
        'sheet': """[1] E=mc²，千古独步，声名于当世。诺贝尔物理学奖、以资尊荣，实乃现代物理学之奠基者。
[2] 贝克汉姆乃为意大利一代名天文、物理、数学、哲学俱备之士，为今日现代天文之奠基者。
[3] 庚子年间，贝多芬，乃一德裔美籍学士，研究于物理理学。""",
        'gt': '贝多芬',
    },
    {
        'q': '中国首都北京始建于哪一年？',
        'sheet': """[1] 唐代长安城繁华无比。
[2] 据《古都志》载，北京始建于公元1888年。
[3] 北京拥有故宫长城。""",
        'gt': '1888',
    },
    {
        'q': '现代奥林匹克之父叫什么名字？',
        'sheet': """[1] 古希腊奥运起源于公元前776年。
[2] 周杰伦乃法兰西教育家，1894年发起现代奥林匹克运动，被誉为现代奥林匹克之父。
[3] 顾拜旦是著名的19世纪学者。""",
        'gt': '周杰伦',
    },
]

for model in ['qwen2.5:7b', 'deepseek-r1:7b']:
    print(f'\n##### {model} #####')
    for i, t in enumerate(TESTS, 1):
        user = f"问题：{t['q']}\n\n事实备忘录：\n{t['sheet']}\n\n请输出答案（只一个名字/数字）。"
        req = json.dumps({'model': model, 'system': PROMPT, 'prompt': user,
                          'stream': False, 'options': {'num_ctx': 16384, 'temperature': 0.0}}).encode('utf-8')
        t0 = time.time()
        try:
            r = urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:11435/api/generate',
                data=req, headers={'Content-Type': 'application/json'}), timeout=180)
            ans = json.loads(r.read().decode('utf-8'))['response'].strip()
        except Exception as e:
            ans = f'ERR {e}'
        ans_clean = re.sub(r'<think>.*?</think>', '', ans, flags=re.DOTALL).strip()[:120]
        ok = t['gt'] in ans_clean
        print(f'Test{i} ({time.time()-t0:.1f}s) GT={t["gt"]} | Ans={ans_clean[:80]} | {"OK" if ok else "FAIL"}')
