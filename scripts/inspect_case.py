import sqlite3, sys
db = sys.argv[1]
needle = sys.argv[2] if len(sys.argv) > 2 else "贝多芬"
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row
cur = c.execute("SELECT COUNT(*) FROM memory_log")
print("rows:", cur.fetchone()[0])
cur = c.execute("SELECT id, substr(content,1,300) AS snippet FROM memory_log WHERE content LIKE ?", (f"%{needle}%",))
rows = cur.fetchall()
print("hits:", len(rows))
for r in rows[:10]:
    print(r["id"], r["snippet"][:300])
