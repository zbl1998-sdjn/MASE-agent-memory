import sys, os, sqlite3
sys.path.insert(0, r"E:\MASE-demo")
sys.path.insert(0, r"E:\MASE-demo\src")
os.environ["MASE_MEMORY_DIR"] = sys.argv[1]
os.environ.setdefault("MASE_CONFIG_PATH", r"E:\MASE-demo\config.json")

from mase import BenchmarkNotetaker

nt = BenchmarkNotetaker()
question = "被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？"
results = nt.search(["__FULL_QUERY__"], full_query=question, limit=20)
print("hits:", len(results))
for r in results[:15]:
    s = r.get("content", "")[:200]
    print(f"id={r['id']} score={r['score']} | {s}")
