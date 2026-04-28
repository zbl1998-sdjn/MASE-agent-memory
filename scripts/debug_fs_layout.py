import os, sys, re
sys.path.insert(0, r"E:\MASE-demo"); sys.path.insert(0, r"E:\MASE-demo\src")
os.environ["MASE_CONFIG_PATH"] = r"E:\MASE-demo\config.lme_glm5.json"
os.environ["MASE_LOCAL_ONLY"] = "1"; os.environ["MASE_LME_LOCAL_ONLY"] = "1"
os.environ["MASE_USE_LLM_JUDGE"] = "0"; os.environ["MASE_ALLOW_CLOUD_MODELS"] = "0"

import mase.engine as eng
captured={}
_orig=eng.MASESystem.call_executor
def patched(self, *args, **kw):
    fs = kw.get("fact_sheet") or (args[1] if len(args)>=2 else "")
    captured["fs"]=fs
    return "Based on current records, I can't answer this question."
eng.MASESystem.call_executor=patched
from benchmarks.runner import BenchmarkRunner
runner=BenchmarkRunner(baseline_profile="none")
runner.run_benchmark("longmemeval_s", sample_limit=1, path=r"E:\MASE-demo\data\longmemeval_official\_debug_one.json")

fs=captured.get("fs","")
if not fs:
    print("STILL EMPTY - check if call_executor was reached")
    import sys; sys.exit(1)
# find segment headers
heads=[]
for m in re.finditer(r"(?m)^[#A-Za-z\u4e00-\u9fff][^\n]{0,80}:\s*$", fs):
    heads.append((m.start(), m.group()))
# also explicit named sections
for kw in ["Question-focused evidence scan","Deterministic temporal","Deterministic aggregate","Deterministic preference",
    "Temporal events","Aggregate ledger","Preference ledger","Operational ledger","CANDIDATE","NOLIMA"]:
    idx=fs.find(kw)
    if idx>=0: heads.append((idx, kw))
for pos, h in sorted(heads)[:30]:
    print(f"  pos={pos:>7} ({pos//4:>5}t) :: {h.strip()[:80]}")
print()
# E-entry positions
ms=list(re.finditer(r"\[E\d+\]",fs))
print(f"E entries: {len(ms)}, first@{ms[0].start()} ({ms[0].start()//4}t), last@{ms[-1].start()} ({ms[-1].start()//4}t)")
print(f"After last E: pos={ms[-1].start()+200}, content[:300]:")
end_e=ms[-1].start()
print(fs[end_e:end_e+300])
print("...")
print(f"\nfs end[-500:]:\n{fs[-500:]}")
