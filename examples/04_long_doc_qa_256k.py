"""
MASE 2.0 — Example 04: Long Document QA @ 256k
复现 README 中的 LV-Eval 256k 88.71% 成绩.

读取 LV-Eval 的 256k 切片样本, 用 MASE 引擎回答, 与官方答案核对.

跑法:
    python examples/04_long_doc_qa_256k.py --limit 10
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5,
                        help="跑多少题. 默认 5, 完整集 188 题.")
    parser.add_argument("--slice", default="256k",
                        choices=["16k", "32k", "64k", "128k", "256k"])
    args = parser.parse_args()

    print(f"复现 LV-Eval EN {args.slice} (前 {args.limit} 题)")
    print("如需完整复现 88.71%, 调用:")
    print(f"    python scripts/run_lveval_dual_gpu.py --lang en --slice {args.slice}")
    print()

    # 完整跑法见 scripts/run_lveval_dual_gpu.py
    # 此 example 用于 GitHub 浏览者快速理解能力, 不重复实现 188 题循环
    from scripts.run_lveval_dual_gpu import run_one_slice  # type: ignore
    run_one_slice(lang="en", slice_=args.slice, limit=args.limit)


if __name__ == "__main__":
    main()
