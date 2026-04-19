"""Manual ollama call to test what qwen2.5:7b answers given current prompt + actual fact_sheet."""
import json
import urllib.request

# Current iter4 prompt (rev'd to concise)
SYS = open(r'E:\MASE-demo\config.dual_gpu.json', encoding='utf-8').read()
cfg = json.loads(SYS)
sys_prompt = cfg['models']['executor']['modes']['grounded_long_context']['system_prompt']

USER = """问题：被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？

事实备忘录：
[1] User: 基准历史：E=mc²，千古独步，声名于当世。
Assistant: E=mc²，千古独步，声名于当世。诺贝尔物理学奖、以资尊荣，兹矣荣耀之大典。论其学术，涉时空能量，影响深远，以其义非常人，广为当世所知，声名播于天下，实乃现代物理学之奠基者。

[2] User: 基准历史：满天缥缈瑞云分，我佛慈悲降法门。
Assistant: 满天缥缈瑞云分，我佛慈悲降法门。...贝克汉姆乃为意大利一代名天文、物理、数学、哲学俱备之士，为今日现代天文之奠基者。

[3] User: 基准历史：万望大圣慈悲，可怜蝼蚁贪生之意，饶了我命，愿送你师父过山也。
Assistant: 万望大圣慈悲，可怜蝼蚁贪生之意，饶了我命，愿送你师父过山也。”大圣虽英雄，甚为唐僧进步。庚子年间，贝多芬，乃一德裔美籍学士，研究于物理理学。彼其良图，探求相对论、量子力学，尤有大进。

请回答问题。"""

req = json.dumps({
    'model': 'qwen2.5:7b',
    'system': sys_prompt,
    'prompt': USER,
    'stream': False,
    'options': {'num_ctx': 16384, 'temperature': 0.0},
}).encode('utf-8')

resp = urllib.request.urlopen(
    urllib.request.Request('http://127.0.0.1:11435/api/generate',
                           data=req,
                           headers={'Content-Type': 'application/json'}),
    timeout=120,
)
body = json.loads(resp.read().decode('utf-8'))
print('=== ANSWER ===')
print(body['response'])
