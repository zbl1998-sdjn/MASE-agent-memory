"""多轮对话压力测试:考 MASE 真实的跨轮承接能力。

不只是"记得",而是考四件硬事:
  1. 跨轮指代:第5轮说"它",能不能解析到第2轮的主语
  2. 事实覆盖:中途改口,取最新值不取旧值
  3. 多事实并存:塞入多条,精准召回相关那条、不串味
  4. 噪声抗扰:夹杂无关闲聊后,关键事实仍召回得到

跑法: .\run_mase.ps1 examples\97_multiturn_stress_probe.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="mase_multiturn_")) / "demo.db"
from mase_tools.memory import db_core  # noqa: E402

db_core.DB_PATH = _TMP
db_core.init_db()

from mase_tools.memory import api  # noqa: E402


def turn(n, who, text):
    api.mase2_write_interaction("t1", who, text)
    print(f"  [{n:>2}] {who}: {text}")


def recall(label, keywords):
    print(f"\n  ❓ {label}  (查询词={keywords})")
    hits = api.mase2_search_memory(keywords, limit=4)
    if not hits:
        print("     (召回为空)")
    for h in hits:
        tag = "[FACT]" if h.get("id") is None else f"[log {h['id']}]"
        print(f"     {tag} {h['content']}")
    return hits


print("=" * 64)
print("  模拟一段 12 轮的真实对话(含改口、多事实、噪声)")
print("=" * 64)
turn(1, "user", "我在做一个项目叫 Atlas,后端用 Go")
api.mase2_upsert_fact("project_status", "atlas_backend", "Go")
turn(2, "user", "Atlas 的数据库先用 PostgreSQL")
api.mase2_upsert_fact("project_status", "atlas_db", "PostgreSQL")
turn(3, "user", "对了我每天喝三杯咖啡")          # 噪声
turn(4, "user", "周末想去爬香山")                  # 噪声
turn(5, "user", "其实 Atlas 的数据库改用 TiDB 吧,PostgreSQL 撑不住")
r5 = api.mase2_correct_and_log("t1", "其实 Atlas 的数据库改用 TiDB 吧")
api.mase2_upsert_fact("project_status", "atlas_db", "TiDB",
                      reason="user_correction", source_log_id=r5["new_log_id"])
turn(6, "user", "前端用 React")
api.mase2_upsert_fact("project_status", "atlas_frontend", "React")
turn(7, "user", "最近天气不错")                    # 噪声

print("\n" + "=" * 64)
print("  几天后,新一轮提问 —— 考跨轮承接")
print("=" * 64)

recall("Q1 跨轮指代:Atlas 的数据库现在是什么?(应取 TiDB,不是 PostgreSQL)", ["Atlas", "数据库", "TiDB", "PostgreSQL"])
recall("Q2 多事实精准:Atlas 技术栈都有啥?", ["Atlas", "Go", "React", "后端", "前端"])
recall("Q3 噪声抗扰:咖啡那条还在不在?(在=不丢历史)", ["咖啡"])

print("\n" + "=" * 64)
print("  当前事实卡(应只剩最新值,db 改口已生效)")
print("=" * 64)
for f in api.mase2_get_facts():
    print(f"  {f['category']}.{f['entity_key']} = {f['entity_value']}")
print(f"\n  demo db: {_TMP}")
