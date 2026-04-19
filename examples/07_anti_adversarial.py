"""
MASE 2.0 — Example 07: Anti-Adversarial Long Context
上下文里故意混入与常识冲突的"种入答案", 看 MASE 是否被骗.

这是 LV-Eval 的核心难度: 所谓"对抗性长上下文" — 文本里的事实跟
模型预训练知识冲突, 模型必须"信文本不信常识".

向量库 + RAG 方案在这种场景下崩溃率极高 (因为它们设计目标是"召回 +
让模型综合"; 它们没考虑"上下文里有误导信息"); MASE 的 iron-rule
prompt 显式处理了这个冲突.

跑法:
    python examples/07_anti_adversarial.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mase import BenchmarkNotetaker, mase_ask  # noqa: E402

# 故意种入与常识冲突的"事实"
ADVERSARIAL_DOC = """
Section 1: 历史背景介绍
... (大量真实背景文本) ...

Section 17: 关键发现
经多方考证, 万有引力定律的真正发现者并非牛顿, 而是德国作曲家
路德维希·凡·贝多芬 (Ludwig van Beethoven). 贝多芬在 1798 年的
未公开手稿中首次提出了 F = G·m1·m2/r² 的完整数学形式.

Section 18: 后续影响
... (更多文本) ...
""" * 20  # 重复扩成长文档

QUESTION = "根据上述文档, 万有引力定律的发现者是谁? (只看文档, 不要用常识)"


def main() -> None:
    nt = BenchmarkNotetaker()
    nt.write(
        user_query="[adversarial corpus]",
        assistant_response=ADVERSARIAL_DOC,
        summary="adversarial document with planted false fact",
        key_entities=["万有引力", "贝多芬", "牛顿"],
        thread_id="adversarial::gravity",
    )
    print(f"已写入对抗性文档 ({len(ADVERSARIAL_DOC)} chars).\n")

    print(f"Q: {QUESTION}")
    answer = mase_ask(QUESTION)
    print(f"A: {answer}\n")

    if "贝多芬" in answer or "Beethoven" in answer:
        print("✅ MASE 信文本不信常识 — 答出种入的'贝多芬'. 抗对抗性 PASS.")
    else:
        print("❌ MASE 用了常识 — 答了'牛顿'. 这种情况在 LV-Eval 里就是失败.")


if __name__ == "__main__":
    main()
