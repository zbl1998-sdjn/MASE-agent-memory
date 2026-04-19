"""MASE 2.0 — Example 06: Auto-correction (UPDATE / DELETE) with audit trail.

Mem0-style "I'm actually 28, not 25" — but with full audit history.
This is THE feature vector libraries cannot ship: they can only append, never
invalidate.

What this demo proves:
  1. A correction phrase ("Actually...", "我之前说错了...") is auto-detected.
  2. The OLD log line is marked superseded (kept for audit, hidden from search).
  3. The Entity-State table updates *and* writes a row to entity_state_history.
  4. Subsequent retrievals only see the NEW value.

Run:
    python examples/06_correct_my_memory.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Use a throwaway DB so the demo is reproducible and non-destructive
_TMP = Path(tempfile.mkdtemp(prefix="mase_demo_06_")) / "demo.db"
from mase_tools.memory import db_core  # noqa: E402
db_core.DB_PATH = _TMP
db_core.init_db()

from mase_tools.memory import api  # noqa: E402


def banner(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> None:
    banner("Step 1 — original facts")
    api.mase2_write_interaction("t1", "user", "My monthly food budget is 800 yuan")
    api.mase2_upsert_fact("finance_budget", "monthly_food_budget", "800")
    api.mase2_write_interaction("t1", "user", "我今年25岁")
    api.mase2_upsert_fact("user_preferences", "age", "25")
    print("  facts:", api.mase2_get_facts())

    banner("Step 2 — user corrects themselves (EN + ZH)")
    r1 = api.mase2_correct_and_log(
        "t1", "Actually, my monthly food budget is 1200 yuan, not 800"
    )
    print("  EN trigger fired:", r1["matched_pattern"])
    print("  superseded log entries:", r1["superseded_count"])
    api.mase2_upsert_fact(
        "finance_budget", "monthly_food_budget", "1200",
        reason="user_correction", source_log_id=r1["new_log_id"],
    )

    r2 = api.mase2_correct_and_log("t1", "我之前说错了, 我其实是28岁")
    print("  ZH trigger fired:", r2["matched_pattern"])
    print("  superseded log entries:", r2["superseded_count"])
    api.mase2_upsert_fact(
        "user_preferences", "age", "28",
        reason="user_correction", source_log_id=r2["new_log_id"],
    )

    banner("Step 3 — search no longer returns old values")
    print("  search('800', 'budget') →")
    for h in api.mase2_search_memory(["800", "budget"]):
        print(f"    [{h['id']}] {h['content']}")
    print("  search('25', '岁') →")
    for h in api.mase2_search_memory(["25", "岁"]):
        print(f"    [{h['id']}] {h['content']}")

    banner("Step 4 — current facts reflect the correction")
    for f in api.mase2_get_facts():
        print(f"  {f['category']}.{f['entity_key']} = {f['entity_value']}")

    banner("Step 5 — full audit trail (this is what vector libraries lack)")
    for h in api.mase2_get_fact_history():
        print(
            f"  {h['category']}.{h['entity_key']}: "
            f"{h['old_value']!r} → {h['new_value']!r} "
            f"(reason={h['supersede_reason']}, src_log_id={h['source_log_id']})"
        )

    print("\n[OK] MASE keeps the *what changed when and why* — Mem0-style UPDATE")
    print("     with 100% transparent SQLite-backed history.")
    print(f"\n   demo db: {_TMP}")


if __name__ == "__main__":
    main()


