"""多写者并发压测(架构切片③,取证型):SQLite WAL 争用真机验证。

模拟真实部署形态:FastAPI sidecar / MCP server / engine 后台线程属不同
进程,同时写同一 DB。三类写者 + 一类读者(真 multiprocessing 进程):

- interaction 写者:``mase2_write_interaction``(memory_log)
- fact 写者:``mase2_upsert_fact``(entity_state)
- governed 写者:``propose_fact``(facts + evidence_spans,多表事务)
- 读者:``mase2_search_memory``(WAL 读不应被写阻塞)

度量:每 worker 成功/locked(SQLITE_BUSY 面)/其它错误、总耗时;结束后
**对账丢写**(期望写入数 vs 实际落库行数)。隔离 DB,不触真实数据。

用法:python -X utf8 scripts/stress_multiwriter.py [writes_per_worker=150]
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _bootstrap(db_path: str) -> None:
    os.environ["MASE_DB_PATH"] = db_path
    os.environ.pop("MASE_MEMORY_DIR", None)
    for p in (str(REPO), str(REPO / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)


def interaction_writer(db_path: str, n: int, worker_id: int, out: mp.Queue) -> None:
    _bootstrap(db_path)
    import sqlite3

    from mase_tools.memory.api import mase2_write_interaction

    ok = locked = other = 0
    for i in range(n):
        try:
            mase2_write_interaction(f"t{worker_id}", "user", f"w{worker_id} message {i} budget {i * 7}")
            ok += 1
        except sqlite3.OperationalError as exc:
            locked += "locked" in str(exc)
            other += "locked" not in str(exc)
        except Exception:
            other += 1
    out.put(("interaction", worker_id, ok, locked, other))


def fact_writer(db_path: str, n: int, worker_id: int, out: mp.Queue) -> None:
    _bootstrap(db_path)
    import sqlite3

    from mase_tools.memory.api import mase2_upsert_fact

    ok = locked = other = 0
    for i in range(n):
        try:
            mase2_upsert_fact("stress", f"key_w{worker_id}_{i}", f"value_{i}")
            ok += 1
        except sqlite3.OperationalError as exc:
            locked += "locked" in str(exc)
            other += "locked" not in str(exc)
        except Exception:
            other += 1
    out.put(("fact", worker_id, ok, locked, other))


def governed_writer(db_path: str, n: int, worker_id: int, out: mp.Queue) -> None:
    _bootstrap(db_path)
    import sqlite3

    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    ok = locked = other = 0
    for i in range(n):
        value = f"gv_{worker_id}_{i}"
        source = f"stress source text: value is {value}."
        try:
            propose_fact(
                FactContract(
                    fact_id=new_fact_id(), entity_id=f"stress:{worker_id}",
                    claim_type="project_fact", subject="stress_governed",
                    predicate=f"gkey_w{worker_id}_{i}", object_value=value,
                    confidence=0.9, observed_at="2026-07-12T00:00:00Z",
                ),
                value, source_type="stress", source_id=f"s{worker_id}",
                trust_level=3, source_full_text=source,
            )
            ok += 1
        except sqlite3.OperationalError as exc:
            locked += "locked" in str(exc)
            other += "locked" not in str(exc)
        except Exception:
            other += 1
    out.put(("governed", worker_id, ok, locked, other))


def reader(db_path: str, stop_flag, out: mp.Queue) -> None:
    _bootstrap(db_path)
    from mase_tools.memory.api import mase2_search_memory

    reads = errors = 0
    while not stop_flag.is_set():
        try:
            mase2_search_memory(["budget"], limit=5)
            reads += 1
        except Exception:
            errors += 1
    out.put(("reader", 0, reads, 0, errors))


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    db_path = str(Path(tempfile.mkdtemp(prefix="mase_stress_")) / "stress.db")
    _bootstrap(db_path)
    # 预热 schema(避免多个进程同时首建表)
    from mase_tools.memory.db_core import get_connection

    get_connection(db_path).close()

    out: mp.Queue = mp.Queue()
    stop = mp.Event()
    workers = [
        mp.Process(target=interaction_writer, args=(db_path, n, 1, out)),
        mp.Process(target=interaction_writer, args=(db_path, n, 2, out)),
        mp.Process(target=fact_writer, args=(db_path, n, 3, out)),
        mp.Process(target=governed_writer, args=(db_path, n, 4, out)),
    ]
    reader_proc = mp.Process(target=reader, args=(db_path, stop, out))

    t0 = time.perf_counter()
    for p in workers:
        p.start()
    reader_proc.start()
    for p in workers:
        p.join(timeout=600)
    stop.set()
    reader_proc.join(timeout=30)
    elapsed = time.perf_counter() - t0

    results = []
    while not out.empty():
        results.append(out.get())

    # 对账丢写:期望 vs 实际
    import sqlite3

    conn = sqlite3.connect(db_path)
    logs = conn.execute("SELECT COUNT(*) FROM memory_log").fetchone()[0]
    # 注意:未知 category 会被 upsert 护栏归一化为 general_facts(设计行为,
    # 首轮压测的"疑似丢写"即此对账口径踩坑)——按 key 前缀对账,不按 category。
    states = conn.execute(
        "SELECT COUNT(*) FROM entity_state WHERE entity_key LIKE 'key_w%'"
    ).fetchone()[0]
    facts = conn.execute("SELECT COUNT(*) FROM facts WHERE subject='stress_governed'").fetchone()[0]
    conn.close()

    writer_rows = [r for r in results if r[0] != "reader"]
    reader_rows = [r for r in results if r[0] == "reader"]
    total_ok = sum(r[2] for r in writer_rows)
    total_locked = sum(r[3] for r in writer_rows)
    total_other = sum(r[4] for r in writer_rows)
    expected = {"memory_log": 2 * n, "entity_state": n, "facts": n}
    actual = {"memory_log": logs, "entity_state": states, "facts": facts}
    report = {
        "writes_per_worker": n,
        "elapsed_seconds": round(elapsed, 1),
        "writer_ok": total_ok, "writer_locked_errors": total_locked, "writer_other_errors": total_other,
        "reader_reads": reader_rows[0][2] if reader_rows else 0,
        "reader_errors": reader_rows[0][4] if reader_rows else 0,
        "expected_rows": expected, "actual_rows": actual,
        "lost_writes": {k: expected[k] - actual[k] for k in expected},
        "throughput_writes_per_sec": round(total_ok / elapsed, 1) if elapsed else 0,
        "per_worker": [{"kind": r[0], "id": r[1], "ok": r[2], "locked": r[3], "other": r[4]} for r in results],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    verdict_ok = total_locked == 0 and total_other == 0 and all(v == 0 for v in report["lost_writes"].values())
    print(f"\nVERDICT: {'PASS - no lost writes, no lock errors' if verdict_ok else 'ISSUES FOUND - see report'}")
    return 0 if verdict_ok else 1


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
