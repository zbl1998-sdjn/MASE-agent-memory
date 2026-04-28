"""P0-B: GLM-5 swap LV-Eval EN 256k+128k (model-swap proof).

Builds an ephemeral config that takes config.dual_gpu.json and swaps
`grounded_long_context_english` to use GLM-5 (cloud) as primary executor,
keeping the SAME iron-rule prompt. Goal: prove the architecture +
prompt are sound, and a bigger base model lifts long slices to 95%+.
"""
import copy
import json
import os
import sys
import time

sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')

# Build patched config
src_cfg = json.load(open(r'E:\MASE-demo\config.dual_gpu.json', encoding='utf-8'))
modes = src_cfg['models']['executor']['modes']
en_mode = copy.deepcopy(modes['grounded_long_context_english'])
preserved_prompt = en_mode['system_prompt']

glm5_mode = {
    'extends': 'grounded_answer',
    'provider': 'anthropic',
    'model_name': 'glm-5',
    'base_url': 'https://open.bigmodel.cn/api/anthropic',
    'api_key_env': 'GLM51_API_KEY',
    'temperature': 0.0,
    'max_tokens': 256,
    'timeout_seconds': 180,
    'system_prompt': preserved_prompt,
    'fallback_models': [
        # Cross-vendor fallback: deepseek-chat -> kimi -> ollama qwen2.5:7b (last-resort local)
        {'provider': 'anthropic', 'model_name': 'deepseek-chat',
         'base_url': 'https://api.deepseek.com/anthropic',
         'api_key_env': 'DEEPSEEK_API_KEY',
         'temperature': 0.0, 'max_tokens': 256, 'timeout_seconds': 180,
         'system_prompt': preserved_prompt},
        {'provider': 'anthropic', 'model_name': 'kimi-k2.5',
         'base_url': 'https://api.kimi.com/coding/',
         'api_key_env': 'KIMI_K25_API_KEY',
         'temperature': 0.0, 'max_tokens': 256, 'timeout_seconds': 180,
         'system_prompt': preserved_prompt},
        {'provider': 'ollama', 'model_name': 'qwen2.5:7b',
         'base_url': 'http://127.0.0.1:11435',
         'ollama_options': {'num_ctx': 16384},
         'temperature': 0.0, 'max_tokens': 256,
         'system_prompt': preserved_prompt},
    ],
}
modes['grounded_long_context_english'] = glm5_mode

cfg_path = r'E:\MASE-demo\config.lveval_glm5_swap.json'
json.dump(src_cfg, open(cfg_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'patched config -> {cfg_path}')

os.environ['MASE_CONFIG_PATH'] = cfg_path
# MASE_MULTIPASS is intentionally NOT popped; callers may enable it for EN long-context.

from benchmarks.runner import BenchmarkRunner

# 256k first (biggest gap to demonstrate); then 128k.
SLICES = ['256k', '128k']
results = {}
runner = BenchmarkRunner(sample_retry_count=0, baseline_profile='off')
t0 = time.time()
for length in SLICES:
    cfg = f'factrecall_en_{length}'
    print(f'\n=== GLM-5 swap {cfg} ===')
    t1 = time.time()
    summary = runner.run_benchmark('lveval', sample_limit=None, config=cfg)
    sb = summary['scoreboard']
    n = sb.get('mase_completed_count', 0)
    p = sb.get('mase_pass_count', 0)
    pct = round(100 * p / max(1, n), 2)
    results[length] = {'n': n, 'pass': p, 'pct': pct, 'elapsed_s': round(time.time()-t1, 1)}
    print(f'{cfg}: {p}/{n} = {pct}%')

print(f'\n=== GLM-5 swap LV-Eval EN ({(time.time()-t0)/60:.1f}min) ===')
for L in SLICES:
    r = results[L]
    print(f'  EN {L}: {r["pass"]}/{r["n"]} = {r["pct"]}%  (was 7B local: 256k=88.71% / 128k=83.23%)')
out_path = r'E:\MASE-demo\scripts\_lveval_en_glm5_swap.json'
json.dump(results, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'-> {out_path}')
