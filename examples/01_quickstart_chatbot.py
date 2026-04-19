"""
MASE 2.0 — Example 01: Quickstart Chatbot
30 行接管 ChatGPT-style 多轮对话, 自动持久化记忆到 SQLite.

跑法:
    python examples/01_quickstart_chatbot.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mase import mase_ask  # noqa: E402


def main() -> None:
    print("MASE chatbot — 输入 'exit' 退出. 你说的话会自动写入 SQLite 记忆.\n")
    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in {"exit", "quit", ":q"}:
            break
        print(f"MASE: {mase_ask(user)}\n")


if __name__ == "__main__":
    main()
