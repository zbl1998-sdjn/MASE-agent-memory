import os, sys, re
sys.path.insert(0, r"E:\MASE-demo"); sys.path.insert(0, r"E:\MASE-demo\src")
os.environ["MASE_CONFIG_PATH"] = r"E:\MASE-demo\config.lme_glm5.json"
os.environ["MASE_ALLOW_CLOUD_MODELS"] = "0"
os.environ["MASE_LOCAL_ONLY"] = "1"
os.environ["MASE_LME_LOCAL_ONLY"] = "1"
os.environ["MASE_USE_LLM_JUDGE"] = "0"

import mase.engine as eng
captured = {}
_orig = eng.MASESystem.call_executor
def patched(self, user_question, fact_sheet, **kw):
    captured["fs"] = fact_sheet
    captured["q"] = user_question
    return "DEBUG_SHORTCIRCUIT"
eng.MASESystem.call_executor = patched

from benchmarks.runner import BenchmarkRunner
PATH = r"E:\MASE-demo\data\longmemeval_official\_debug_one.json"
runner = BenchmarkRunner(baseline_profile="none")
runner.run_benchmark("longmemeval_s", sample_limit=1, path=PATH)

fs = captured.get("fs", "")
print("FS total len:", len(fs))
print("approx tokens:", len(fs)//4)
# find evidence
for kw in ("45 minutes", "commute, which", "daily commute"):
    idx = fs.lower().find(kw.lower())
    print(f"  '{kw}': pos={idx}")
# What's at end vs start? Show outline
# Count entries by [En] pattern
ms = list(re.finditer(r"\[E(\d+)\]", fs))
print(f"E-entries: {len(ms)} (last={ms[-1].group(1) if ms else None})")
# find [E*] entry containing "commute"
for m in ms:
    start = m.start()
    end = ms[ms.index(m)+1].start() if ms.index(m)+1 < len(ms) else min(len(fs), start+800)
    chunk = fs[start:end]
    if "commute" in chunk.lower() and ("45" in chunk or "minute" in chunk.lower()):
        print(f"\n>>> RELEVANT FOUND at pos={start}, entry={m.group(0)}")
        print(chunk[:800])
        break
else:
    print("\n!!! No entry with both 'commute' and '45/minute' in fact_sheet")
# check window radius - maybe evidence was retrieved but not as keyword match
# search for raw "45 minutes each way"
idx = fs.find("45 minutes each way")
print(f"\nGT phrase '45 minutes each way' pos={idx}")
if idx >= 0:
    ctx = fs[max(0,idx-200):idx+400]
    print("CONTEXT:")
    print(ctx)
