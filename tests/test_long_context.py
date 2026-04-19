from __future__ import annotations

from benchmarks.baseline import baseline_ask
from mase import mase_ask


def run_mase_scenario() -> str:
    print("=== MASE 30轮回忆测试 ===")
    mase_ask("请记住：我们公司的营销预算是350万元，线上投放占60%。")

    for index in range(2, 30):
        mase_ask(f"闲聊第{index}轮：今天天气不错。")

    answer = mase_ask("我们最开始聊的那个营销预算，是多少？线上投放占多少？")
    print("=== MASE 最终回答 ===")
    print(answer)
    return answer


def run_baseline_scenario() -> str:
    print("=== Baseline 30轮对比测试 ===")
    conversation: list[dict[str, str]] = []
    baseline_ask(conversation, "请记住：我们公司的营销预算是350万元，线上投放占60%。")

    for index in range(2, 30):
        baseline_ask(conversation, f"闲聊第{index}轮：今天天气不错。")

    answer = baseline_ask(conversation, "我们最开始聊的那个营销预算，是多少？线上投放占多少？")
    print("=== Baseline 最终回答 ===")
    print(answer)
    return answer


if __name__ == "__main__":
    run_mase_scenario()
    print()
    run_baseline_scenario()
