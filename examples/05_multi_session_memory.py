"""
MASE 2.0 — Example 05: Multi-Session Memory
复现 LongMemEval 跨 session 推理场景.

模拟用户 30 天里的 5 个会话, MASE 自动把每个会话写入 SQLite,
最后跨 session 提问 — 必须 aggregate 多个 session 的事实才能答对.

向量库会"召回最近的 1-2 段", MASE 走 BM25 + topic_tokens 全召回.

跑法:
    python examples/05_multi_session_memory.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mase import BenchmarkNotetaker, mase_ask  # noqa: E402


SESSIONS = [
    ("2026-03-01", "我开始跑步训练, 目标半马."),
    ("2026-03-08", "今天跑了 10km, 用时 58 分钟."),
    ("2026-03-15", "今天跑了 15km, 用时 1 小时 32 分."),
    ("2026-03-22", "今天跑了 18km, 用时 1 小时 55 分."),
    ("2026-03-29", "今天报名了 4 月 12 日的半马比赛."),
]

QUESTIONS = [
    "我半马训练总共跑了多少公里?",
    "我最近一次的配速大约是多少?",
    "我半马比赛是哪天?",
]


def main() -> None:
    nt = BenchmarkNotetaker()
    for date, text in SESSIONS:
        nt.write(
            user_query=text,
            assistant_response="",
            summary=f"running log {date}",
            key_entities=["半马", "跑步", date],
            thread_id=f"session::{date}",
        )
    print(f"已写入 {len(SESSIONS)} 个 session.\n")

    for q in QUESTIONS:
        print(f"Q: {q}")
        print(f"A: {mase_ask(q)}\n")


if __name__ == "__main__":
    main()
