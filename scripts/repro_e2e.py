import sys, os, io
sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")
os.environ["MASE_MEMORY_DIR"] = sys.argv[1]
os.environ["MASE_TASK_TYPE"] = "long_context_qa"
os.environ.setdefault("MASE_CONFIG_PATH", r"E:\MASE-demo\config.json")

from mase import MASESystem

system = MASESystem()
question = sys.argv[2] if len(sys.argv) > 2 else "被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？"
trace = system.run_with_trace(question, log=False, forced_route={"action": "search_memory", "keywords": ["__FULL_QUERY__"]})
out = []
out.append("=== ANSWER ===")
out.append(trace.answer)
out.append("=== FACT SHEET ===")
out.append(trace.fact_sheet[:3000])
out.append("=== SEARCH RESULTS ===")
for r in trace.search_results[:5]:
    out.append(f"-- score={r.get('score')} {r.get('content','')[:300]}")
out.append("=== EXEC TARGET ===")
out.append(repr(trace.executor_target))
out.append("=== PLANNER ===")
out.append(f"source={trace.planner.source} text={trace.planner.text}")
out.append("=== INSTRUCTION PACKAGE ===")
out.append(str(trace.evidence_assessment.get("instruction_package", "")))
text = "\n".join(out)
with io.open("scripts/_last_repro.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text.encode("ascii", "replace").decode("ascii"))

