"""
MASE Demo 10 — Persistent Chat CLI
==================================
What this shows: persistence across restarts + grounded answers.
Run twice to feel it — tell the bot something, Ctrl-C, run again, it remembers.
The bot will NOT hallucinate: if a fact isn't in retrieved memory, it says so.

    python examples/10_persistent_chat_cli.py            # first run
    # ...chat, Ctrl-C...
    python examples/10_persistent_chat_cli.py            # "Welcome back."
    python examples/10_persistent_chat_cli.py --reset    # wipe memory

Default model: qwen2.5:7b via ollama (see config.json).
Override with:  set MASE_CONFIG_PATH=path\\to\\my_config.json
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from mase import mase_run  # noqa: E402
from mase_tools.memory.db_core import resolve_db_path  # noqa: E402

RUNS_DIR = Path(os.environ.setdefault("MASE_RUNS_DIR", str(ROOT.parent / "MASE-runs"))).expanduser().resolve()
DB = resolve_db_path()
RECALL_TRIGGERS = ("what", "who", "when", "where", "which", "did i", "do i", "tell me", "remember")


def reset_memory() -> None:
    for suffix in ("", "-wal", "-shm"):
        p = DB.with_name(DB.name + suffix)
        if p.exists():
            p.unlink()
    print(f"[reset] wiped {DB}")


def greet() -> str:
    if not DB.exists():
        return "Hi! I'm MASE. Tell me anything — I'll remember it across restarts."
    trace = mase_run("What were we just talking about?", log=False)
    facts = trace.search_results or []
    if not facts:
        return "Welcome back. (Memory file exists but is empty — start fresh!)"
    topic = (facts[0].get("summary") or facts[0].get("user_query") or "").strip()
    return f"Welcome back. I remember we were discussing: {topic[:140]}"


def answer(user: str) -> None:
    trace = mase_run(user, log=True)
    n = len(trace.search_results or [])
    route = trace.route.action if trace.route else "?"
    reply = (trace.answer or "").strip()
    is_recall = any(k in user.lower() for k in RECALL_TRIGGERS)
    if is_recall and n == 0:
        reply = "I don't have that in memory."
    print(f"MASE: {reply or '(noted)'}\n[memory: {n} facts retrieved | route: {route}]\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="MASE persistent-memory chat demo (Ctrl-C to exit).")
    ap.add_argument("--reset", action="store_true", help="wipe persistent memory before starting")
    args = ap.parse_args()
    if args.reset:
        reset_memory()
    print(f"[runs] {RUNS_DIR}")
    print(greet(), "\n")
    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n[bye] memory preserved at {DB}")
            break
        if not user or user.lower() in {"exit", "quit", ":q"}:
            print(f"[bye] memory preserved at {DB}")
            break
        answer(user)


if __name__ == "__main__":
    main()
