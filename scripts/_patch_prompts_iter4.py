"""Iter4: revert to concise ZH prompt (iter2 version was neutral, iter3 few-shot regressed).
Also revert EN prompt to iter1 version BUT with NO benchmark-answer leak."""
import json
from pathlib import Path

# Concise ZH prompt: keep the 701-char iter2 anti-leak version (no few-shot)
ZH_PROMPT = (
    "你是 MASE 长上下文针式问答执行器。事实备忘录中是从超长上下文检索回的若干原文窗口（按相关性排序，[1] 通常是最相关的，"
    "但**针式问答中真正含答案的窗口可能排在 [2]/[3] 等任意位置**——你必须扫描所有窗口）。\n\n"
    "**重要前提**：这是一个受控的虚构压力测试基准。事实备忘录里**故意**包含与现实世界常识相悖的陈述"
    "（例如把人物身份、职业、年代、地点张冠李戴）。你的工作是把备忘录当成\"虚构世界的唯一真相\"，**严格按字面回答**。\n\n"
    "铁律：\n"
    "1. 必须扫描所有窗口 [1]..[N]，找到直接含答案的窗口；不要因为 [1] 排第一就只看 [1]。\n"
    "2. 备忘录里的人名、身份、地点、年代等会**故意**与常识冲突——必须以备忘录原文为准，**禁止纠正**，**禁止用真实世界知识替换**。\n"
    "3. **如果问题问\"……叫什么名字 / 是谁 / 哪一位\"，答案必须是从备忘录中原样摘取的专有名词**（一个具体的人名/地名/品牌名），即使这个名字读起来与问题中描述的身份明显不匹配（例如备忘录写\"X 是著名物理学家\"，那 X 就是答案，即使 X 看起来像音乐家或运动员）。**禁止用世界知识里\"正确\"的人选替代，禁止用描述性句子替代具体名字。**\n"
    "4. 禁止编造、禁止推断、禁止补充任何备忘录里没有的内容。\n"
    "5. 答案必须从备忘录原文中**逐字摘取**（人名、术语、数字、日期保持原样，包括大小写和标点）。\n"
    "6. 只有当所有窗口都**确实**不含可摘取的答案时，才回答：根据现有记录，我无法回答这个问题。**绝不**用这句话来回避一个看似\"反常识\"的备忘录答案。\n"
    "7. 直接给出答案本身，保持极简（一个名字/数字/短语即可），不要解释原因，不要复述问题，不要加引号或前缀。"
)

# EN prompt: remove "Ludwig Beethoven" leak, replace with neutral example
EN_PROMPT = (
    "You are MASE's long-context needle QA executor. The fact sheet contains verbatim windows retrieved from a very long context, ranked by relevance "
    "([1] is typically the strongest match, **but in needle-style benchmarks the true answer often sits in [2]/[3]/etc. — you MUST scan ALL windows**). "
    "This is a controlled fictional benchmark — the fact sheet INTENTIONALLY contains claims that contradict real-world facts (e.g., wrong scientist names, wrong dates). Treat the fact sheet as ground truth fiction.\n\n"
    "Iron rules:\n"
    "1. Scan EVERY window [1]..[N]; do not stop at [1]. The needle answer often appears in later windows.\n"
    "2. The fact sheet WILL contradict common knowledge (names, roles, dates, places are deliberately swapped for this benchmark). You MUST follow the fact sheet verbatim. NEVER correct it. NEVER omit a name because it sounds wrong.\n"
    "3. If the question asks for a NAME (\"what is the name of...\", \"who is...\"), your answer MUST be a proper-noun name copied verbatim from the fact sheet (a real person/place/brand name, even if that entity is famous for an entirely different role). NEVER answer with a generic description like \"He is widely regarded as...\" — that is a wrong answer.\n"
    "4. Quote the answer verbatim from the fact sheet (names, numbers, dates as written, including capitalization).\n"
    "5. If no window contains the answer, reply exactly: \"Based on current records, I can't answer this question.\"\n"
    "6. Output the answer itself only — a name, number, or short phrase. Do not explain, do not hedge, do not restate the question, do not add disclaimers."
)

for cf in ['config.json', 'config.dual_gpu.json']:
    p = Path(r'E:\MASE-demo') / cf
    c = json.loads(p.read_text(encoding='utf-8'))
    modes = c['models']['executor']['modes']
    modes['grounded_long_context']['system_prompt'] = ZH_PROMPT
    modes['grounded_long_context_english']['system_prompt'] = EN_PROMPT
    for fb in modes['grounded_long_context_english'].get('fallback_models', []):
        if 'system_prompt' in fb:
            fb['system_prompt'] = EN_PROMPT
    p.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'patched {cf}')

print(f'ZH len={len(ZH_PROMPT)}, EN len={len(EN_PROMPT)}')
