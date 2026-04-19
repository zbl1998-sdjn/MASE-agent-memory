"""
MASE 2.0 — Example 09: Resume After Crash
演示"凌晨 1:49 Windows 强制重启"场景: 进程被 kill, 重启后记忆原样回来.

向量库方案需要"重建索引 + 热身", MASE 是 SQLite 文件, 零冷启动.

跑法 (分两次):
    # Phase 1: 写入记忆然后退出
    python examples/09_resume_after_crash.py phase1

    # 模拟系统重启 (你可以真的重启电脑试试)

    # Phase 2: 验证记忆还在
    python examples/09_resume_after_crash.py phase2
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mase import mase_ask  # noqa: E402


def phase1() -> None:
    facts = [
        "我叫张伟, 今年 31 岁, 在上海做产品经理.",
        "我老婆叫小美, 我们 2024 年结婚的.",
        "我们家的猫叫'葡萄', 是一只英短.",
    ]
    for f in facts:
        mase_ask(f)
    print("\n[phase1] 已写入 3 条核心事实到 SQLite (data/mase_memory.db).")
    print("现在你可以:")
    print("  1. 关掉这个进程 (或 kill -9)")
    print("  2. 重启电脑")
    print("  3. 跑 phase2 看记忆还在不在")


def phase2() -> None:
    questions = [
        "我叫什么?",
        "我多大?",
        "我老婆叫什么名字?",
        "我家猫叫什么?",
    ]
    print("[phase2] 验证记忆 (假设刚刚经历了一次 kill -9 / 系统重启):\n")
    for q in questions:
        print(f"Q: {q}")
        print(f"A: {mase_ask(q)}\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "phase1"
    {"phase1": phase1, "phase2": phase2}[cmd]()
