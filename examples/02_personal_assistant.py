"""
MASE 2.0 — Example 02: Personal Assistant
演示跨轮偏好记忆: 第 1 轮告诉 MASE 偏好 → 第 N 轮直接问, 不需重复.

向量库方案常常会"两条都召回 + 模型分不清", MASE 走 Entity Fact Sheet UPSERT,
最新偏好直接覆盖旧偏好.

跑法:
    python examples/02_personal_assistant.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mase import mase_ask  # noqa: E402

SCRIPT = [
    "我叫小明, 今年 27 岁.",
    "我特别爱吃辣, 不能吃香菜.",
    "我在北京, 周末喜欢爬山.",
    "推荐一下周末活动?",
    "我多大?",
    "我能吃香菜吗?",
]


def main() -> None:
    for turn, msg in enumerate(SCRIPT, 1):
        print(f"\n[Turn {turn}] You: {msg}")
        print(f"[Turn {turn}] MASE: {mase_ask(msg)}")


if __name__ == "__main__":
    main()
