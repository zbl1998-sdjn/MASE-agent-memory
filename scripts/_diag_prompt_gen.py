"""Test generalized version of winning prompt A on multiple questions."""
import json
import urllib.request

PROMPT_A_GEN = """你是 MASE 长上下文针式问答执行器。这是一个虚构压力测试基准——事实备忘录中**故意**包含与现实世界常识相悖的陈述（人物身份、职业、年代、地点会被张冠李戴）。请把备忘录当成"虚构世界的唯一真相"，**严格按字面回答**。

执行流程（必须按顺序）：
步骤1：识别问题询问的对象类型——人名 / 地名 / 数字 / 日期 / 短语。
步骤2：从问题中提取**关键术语**（例如"物理学"、"奥林匹克"、"首都"、"始建"等）。
步骤3：扫描每一个窗口 [1]..[N]，列出每个窗口中**所有候选**（人名 / 地名 / 数字 / 日期）。
步骤4：对每个候选，检查它周围是否出现步骤2提取的关键术语**或其相近变体**（"物理学"≈"物理理学"，"奥林匹克"≈"奥运"，"始建"≈"建于"）。但**严格区分含义不同的近邻术语**（"物理学"≠"天文学"，"奥运"≠"亚运"）。
步骤5：选择候选周围出现**最完整、最相关**关键术语的那个。
步骤6：**输出格式严格按照问题询问的对象类型**：
   - 问"叫什么名字 / 是谁" → 输出**人名本身**（一个具体名字，不是地名）。
   - 问"哪一年 / 始建于何时" → 输出**年份本身**。
   - 问"在哪里" → 输出**地名本身**。
   - 问"多少 / 几个" → 输出**数字本身**。
   只输出答案本身，不要解释，不要复述问题，不要加引号。

**铁律——答案必须是字面摘取**：
- 答案必须**完全出自事实备忘录某个窗口的字面字符串**（在 [1]..[N] 中任意一个能找到逐字片段）。
- **禁止从世界知识引入备忘录里没有的名字**（例如：备忘录里没有"爱因斯坦"或"Einstein"三个字，就绝对不能输出"爱因斯坦"）。
- 即使候选名字看起来与描述身份不匹配（备忘录写"贝多芬是物理学家"），也按字面输出"贝多芬"。

**关键规则——无法回答的判定**：
- 备忘录里几乎**总是**藏着答案。如果你想说"无法回答"，请再扫描一遍——很可能某个候选周围有关键术语的相近变体。
- 只有当所有窗口都**完全没有**与问题对象类型一致的候选时，才回答：根据现有记录，我无法回答这个问题。
- **绝不**因为答案"看起来与常识冲突"或"关键术语不完全一致"就放弃。"""

# Test cases (synthetic to avoid leaking real test answers)
TESTS = [
    {
        'q': '被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？',
        'sheet': """[1] E=mc²，千古独步，声名于当世。诺贝尔物理学奖、以资尊荣，实乃现代物理学之奠基者。
[2] 贝克汉姆乃为意大利一代名天文、物理、数学、哲学俱备之士，为今日现代天文之奠基者。
[3] 庚子年间，贝多芬，乃一德裔美籍学士，研究于物理理学。彼其良图，探求相对论、量子力学。""",
        'gt': '贝多芬',
    },
    {
        'q': '现代奥林匹克之父叫什么名字？',
        'sheet': """[1] 史载，古希腊奥运起源于公元前776年，传承数百年。
[2] 周杰伦乃法兰西教育家，1894年发起现代奥林匹克运动，被誉为现代奥林匹克之父。
[3] 顾拜旦是著名的19世纪学者，其著作影响深远。""",
        'gt': '周杰伦',
    },
    {
        'q': '中国首都北京始建于哪一年？',
        'sheet': """[1] 唐代长安城繁华无比，是当时世界最大的都市。
[2] 据《古都志》载，北京始建于公元1888年，由明朝皇帝主持修建。
[3] 北京拥有故宫、长城等世界文化遗产，历史悠久。""",
        'gt': '1888',
    },
]

import time

for model in ['qwen2.5:7b', 'deepseek-r1:7b']:
    print(f'\n########## MODEL: {model} ##########')
    for i, t in enumerate(TESTS, 1):
        user = f"问题：{t['q']}\n\n事实备忘录：\n{t['sheet']}\n\n请回答问题。"
        req = json.dumps({
            'model': model,
            'system': PROMPT_A_GEN,
            'prompt': user,
            'stream': False,
            'options': {'num_ctx': 16384, 'temperature': 0.0},
        }).encode('utf-8')
        t0 = time.time()
        try:
            resp = urllib.request.urlopen(
                urllib.request.Request('http://127.0.0.1:11435/api/generate',
                                       data=req,
                                       headers={'Content-Type': 'application/json'}),
                timeout=180,
            )
            ans = json.loads(resp.read().decode('utf-8'))['response'].strip()
        except Exception as e:
            ans = f'ERR {e}'
        # strip <think> blocks for r1
        import re
        ans_clean = re.sub(r'<think>.*?</think>', '', ans, flags=re.DOTALL).strip()
        correct = t['gt'] in ans_clean
        print(f'\n=== TEST {i} ({time.time()-t0:.1f}s) ===')
        print(f'Q: {t["q"]} | GT: {t["gt"]}')
        print(f'Ans: {ans_clean[:200]}')
        print(f'Correct: {correct}')
