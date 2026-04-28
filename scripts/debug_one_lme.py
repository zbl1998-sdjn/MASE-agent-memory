"""Debug single LME case: dump fact_sheet sent to executor."""
import json, os, sys
sys.path.insert(0, r"E:\MASE-demo"); sys.path.insert(0, r"E:\MASE-demo\src")
os.environ["MASE_CONFIG_PATH"] = r"E:\MASE-demo\config.lme_glm5.json"
os.environ["MASE_ALLOW_CLOUD_MODELS"] = "0"
os.environ["MASE_LOCAL_ONLY"] = "1"
os.environ["MASE_LME_LOCAL_ONLY"] = "1"
os.environ["MASE_USE_LLM_JUDGE"] = "0"
os.environ["MASE_DEBUG_DUMP_FACTSHEET"] = "1"

from benchmarks.runner import BenchmarkRunner

PATH = r"E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json"
data = json.load(open(PATH, encoding="utf-8"))
target_qid = "118b2229"
hits = [s for s in data if s.get("question_id") == target_qid]
print("found:", len(hits))
if not hits:
    # try by id field
    hits = [s for s in data if s.get("id") == target_qid]
    print("found by id:", len(hits))
if not hits:
    # fall back to first single-session-user
    hits = [s for s in data if s.get("question_type") == "single-session-user"][:1]

# patch engine.call_executor to print fact_sheet
import mase.engine as eng
_orig = eng.MASESystem.call_executor
def patched(self, user_question, fact_sheet, **kw):
    print("=" * 70)
    print("Q:", user_question)
    print("-" * 70)
    print("FACT SHEET (first 3500 chars):")
    print(fact_sheet[:3500])
    print("-" * 70, "FS_LEN=", len(fact_sheet))
    ans = _orig(self, user_question, fact_sheet, **kw)
    print("ANS:", ans[:500])
    return ans
eng.MASESystem.call_executor = patched

# write hit to a tmp dataset file
tmp = r"E:\MASE-demo\data\longmemeval_official\_debug_one.json"
json.dump(hits[:1], open(tmp, "w", encoding="utf-8"))
runner = BenchmarkRunner(baseline_profile="none")
report = runner.run_benchmark("longmemeval_s", sample_limit=1, path=tmp)
results = report.get("results", [])
print("\nresult score:", (results[0]["mase"].get("score") or {}).get("all_matched"))
