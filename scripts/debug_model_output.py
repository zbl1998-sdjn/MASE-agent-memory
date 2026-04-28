import os, sys
sys.path.insert(0, r"E:\MASE-demo"); sys.path.insert(0, r"E:\MASE-demo\src")
os.environ["MASE_CONFIG_PATH"] = r"E:\MASE-demo\config.lme_glm5.json"
os.environ["MASE_ALLOW_CLOUD_MODELS"] = "0"
os.environ["MASE_LOCAL_ONLY"] = "1"
os.environ["MASE_LME_LOCAL_ONLY"] = "1"
os.environ["MASE_USE_LLM_JUDGE"] = "0"

from benchmarks.runner import BenchmarkRunner
import mase.model_interface as mi

_orig = mi.ModelInterface.chat
def patched(self, agent_type, messages, mode=None, tools=None, override_system_prompt=None, prompt_key="system_prompt"):
    out = _orig(self, agent_type, messages, mode=mode, tools=tools, override_system_prompt=override_system_prompt, prompt_key=prompt_key)
    if agent_type == "executor":
        print("=== EXECUTOR CALL ===")
        print("mode:", mode)
        if isinstance(out, dict):
            c = (out.get("message") or {}).get("content", "") or out.get("content", "")
        else:
            c = str(out)
        print("raw out len:", len(c) if c else 0)
        print("raw out (first 800):", repr(c[:800]))
        if messages:
            last = messages[-1].get("content", "")
            print("last_user len:", len(last))
            print("last_user preview last 600:", repr(last[-600:]))
    return out
mi.ModelInterface.chat = patched

PATH = r"E:\MASE-demo\data\longmemeval_official\_debug_one.json"
runner = BenchmarkRunner(baseline_profile="none")
report = runner.run_benchmark("longmemeval_s", sample_limit=1, path=PATH)
results = report.get("results", [])
print("SCORE:", (results[0]["mase"].get("score") or {}).get("all_matched"))
