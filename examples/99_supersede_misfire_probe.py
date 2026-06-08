"""误伤探针:验证 "应该是" 触发的 supersede 弹片范围。

用临时库,不碰正式记忆。跑法:
    python examples/99_supersede_misfire_probe.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="mase_misfire_")) / "demo.db"
from mase_tools.memory import db_core  # noqa: E402

db_core.DB_PATH = _TMP
db_core.init_db()

from mase_tools.memory import api  # noqa: E402

OLD_LINES = [
    "周五会议改到 4 点了",
    "我的预算是 3000 元",
    "1234567890",
    "我喜欢喝美式咖啡",
]

for s in OLD_LINES:
    api.mase2_write_interaction("t1", "user", s)

print("=" * 56)
print("  新话进场: 明天的会议应该是3点开始  (并非改口!)")
print("=" * 56)
r = api.mase2_correct_and_log("t1", "明天的会议应该是3点开始")
print("  is_correction :", r["is_correction"])
print("  matched       :", r["matched_pattern"])
print("  keywords      :", r.get("matched_keywords"))
print("  superseded    :", r["superseded_count"], "行被盖章")

print("\n  全库验尸:")
conn = sqlite3.connect(_TMP)
conn.row_factory = sqlite3.Row
for row in conn.execute(
    "SELECT id, content, superseded_at FROM memory_log ORDER BY id"
):
    flag = "[X 已盖章]" if row["superseded_at"] else "[OK 存活]"
    print(f"    [{row['id']}] {flag} {row['content']}")
print(f"\n  demo db: {_TMP}")
