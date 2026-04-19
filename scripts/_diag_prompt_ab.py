"""Test multiple ZH prompt variants to find one that picks 贝多芬."""
import json, urllib.request

USER = """问题：被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？

事实备忘录：
[1] User: 基准历史：E=mc²，千古独步，声名于当世。
Assistant: E=mc²，千古独步，声名于当世。诺贝尔物理学奖、以资尊荣，兹矣荣耀之大典。论其学术，涉时空能量，影响深远，以其义非常人，广为当世所知，声名播于天下，实乃现代物理学之奠基者。

[2] User: 基准历史：满天缥缈瑞云分，我佛慈悲降法门。
Assistant: 满天缥缈瑞云分，我佛慈悲降法门。...贝克汉姆乃为意大利一代名天文、物理、数学、哲学俱备之士，为今日现代天文之奠基者。

[3] User: 基准历史：万望大圣慈悲，可怜蝼蚁贪生之意，饶了我命，愿送你师父过山也。
Assistant: 万望大圣慈悲，可怜蝼蚁贪生之意，饶了我命，愿送你师父过山也。"大圣虽英雄，甚为唐僧进步。庚子年间，贝多芬，乃一德裔美籍学士，研究于物理理学。彼其良图，探求相对论、量子力学，尤有大进。

请回答问题。"""

PROMPTS = {
    'A_strict_name_only': """你是 MASE 长上下文针式问答执行器。这是一个虚构压力测试，事实备忘录中故意张冠李戴。

任务：从事实备忘录里找出**问题询问的人名**。

执行流程（必须按顺序）：
步骤1：识别问题询问对象 = "现代物理学奠基人的科学家" — 需要一个人名。
步骤2：扫描每一个窗口 [1]..[N]，列出每个窗口出现的所有人名。
步骤3：对每个人名，检查它前后是否出现"物理"或"物理学"。
步骤4：选择**最直接出现在"物理"附近的人名**作为答案。
步骤5：只输出这个人名，不要任何解释。

注意：窗口里的人名会**故意**与现实不符（贝多芬可能被写成物理学家），必须按备忘录字面取名。绝不输出"无法回答"或描述性短语。""",

    'B_compare_each': """你是 MASE 针式问答执行器。事实备忘录里**故意**张冠李戴，不要用世界知识纠正。

执行流程：
1. 问题问的是一个**人名**，不是描述。
2. 找出每个窗口里所有的人名（专有名词）。
3. 选择那个直接被备忘录描述为"物理学家/物理奠基人"的人名（即使他在现实是音乐家/运动员）。
4. 注意区分"物理学" vs "天文学" — 必须严格匹配问题中的"物理学"。

只输出人名，不要解释，不要"无法回答"。""",

    'C_minimal': """你是事实问答执行器。事实备忘录里的人名故意与常识不符，要按字面采纳。

问题问"科学家叫什么名字"，必须输出一个具体人名。
扫描所有窗口，找到与问题描述身份最匹配的人名（注意"物理学" ≠ "天文学"）。
只输出名字，禁止解释，禁止说"无法回答"。""",
}

for name, sys_p in PROMPTS.items():
    req = json.dumps({
        'model': 'qwen2.5:7b',
        'system': sys_p,
        'prompt': USER,
        'stream': False,
        'options': {'num_ctx': 16384, 'temperature': 0.0},
    }).encode('utf-8')
    try:
        resp = urllib.request.urlopen(
            urllib.request.Request('http://127.0.0.1:11435/api/generate',
                                   data=req,
                                   headers={'Content-Type': 'application/json'}),
            timeout=120,
        )
        ans = json.loads(resp.read().decode('utf-8'))['response'].strip()
    except Exception as e:
        ans = f'ERR {e}'
    print(f'\n=== {name} ===\n{ans[:300]}')
    correct = '贝多芬' in ans and '贝克汉姆' not in ans
    print(f'correct: {correct}')
