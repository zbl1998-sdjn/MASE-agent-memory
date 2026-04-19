"""P0-A: bare qwen2.5:7b LV-Eval EN baseline (no MASE, no retrieval).

Purpose: prove MASE architecture is the actual contributor by showing that
feeding the entire long context directly into qwen2.5:7b (with native 32k window
truncating the rest) collapses on 64k+ slices. The contrast vs MASE numbers
becomes the headline GitHub claim.

Runs slices 64k / 128k / 256k EN (where the gap is largest).
"""
import os, sys, json, time
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')

from benchmarks.registry import load_benchmark_samples
from benchmarks.baseline import baseline_ask_with_metrics
from benchmarks.scoring import score_sample
from benchmarks.runner import _build_baseline_conversation, BASELINE_SYSTEM_PROMPT

SLICES = ['64k', '128k', '256k']
PROFILE = 'ollama-qwen25-7b'
results = {}
t0 = time.time()

for length in SLICES:
    cfg = f'factrecall_en_{length}'
    print(f'\n=== bare baseline {cfg} ===')
    samples = load_benchmark_samples('lveval', sample_limit=None, config=cfg)
    print(f'loaded {len(samples)} samples')
    t1 = time.time()
    passed = 0
    for i, s in enumerate(samples, 1):
        try:
            conv = _build_baseline_conversation(s)
            r = baseline_ask_with_metrics(
                conv, s.question,
                profile=PROFILE,
                system_prompt=BASELINE_SYSTEM_PROMPT,
                overrides={'timeout_seconds': 60},
            )
            ans = str(r['answer'])
        except Exception as e:
            ans = f'__ERR__ {type(e).__name__}'
        sc = score_sample(s, ans)
        if sc.get('all_matched'):
            passed += 1
        if i % 20 == 0 or i == len(samples):
            elapsed = time.time() - t1
            avg = elapsed / i
            eta = avg * (len(samples) - i)
            print(f'  [{i}/{len(samples)}] pass={passed} ({100*passed/i:.1f}%) avg={avg:.1f}s eta={eta:.0f}s')
    n = len(samples)
    pct = round(100 * passed / max(1, n), 2)
    results[length] = {'n': n, 'pass': passed, 'pct': pct, 'elapsed_s': round(time.time()-t1, 1)}
    print(f'  -> {cfg}: {passed}/{n} = {pct}%')

print(f'\n=== bare qwen2.5:7b LV-Eval EN baseline ({(time.time()-t0)/60:.1f} min) ===')
for L in SLICES:
    r = results[L]
    print(f'  EN {L}: {r["pass"]}/{r["n"]} = {r["pct"]}%')
out_path = r'E:\MASE-demo\scripts\_lveval_en_bare_baseline.json'
json.dump(results, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'-> {out_path}')
