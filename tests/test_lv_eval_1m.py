#!/usr/bin/env python3
"""
测试 LV-Eval 1M 中文测试数据集 (test_001.json ~ test_050.json)
使用 MASE 框架对长上下文理解能力进行评测
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from benchmarks.runner import BenchmarkRunner
from benchmarks.schemas import BenchmarkSample

# LV-Eval 1M calls live model backends and takes minutes per sample.
pytestmark = [pytest.mark.integration, pytest.mark.slow]


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
TEST_DATA_DIR = Path(r"C:\Users\Administrator\AppData\Local\Programs\CC Switch\lv_eval_1m_test_cases")


def load_test_case(case_id: int) -> dict[str, Any]:
    """从 JSON 文件加载单个测试用例"""
    file_path = TEST_DATA_DIR / f"test_{case_id:03d}.json"
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def convert_to_benchmark_cases() -> list[BenchmarkSample]:
    """将 LV-Eval 数据转换为 MASE BenchmarkSample 格式"""
    cases: list[BenchmarkSample] = []
    
    for case_id in range(1, 51):
        try:
            raw = load_test_case(case_id)
            
            test_case = raw["test_case"]
            context = raw["context"]
            metadata = raw["metadata"]
            
            benchmark_case = BenchmarkSample(
                id=f"lv_eval_1m_{case_id:03d}",
                benchmark="lv_eval_1m",
                task_type="long_context_qa",
                question=test_case["question"],
                ground_truth=test_case["answer"],
                context=context,
                metadata={
                    "difficulty": test_case["difficulty"],
                    "type": test_case["type"],
                    "position": str(test_case["position"]),
                    "category": test_case.get("category", "unknown"),
                    "needle": test_case["needle"],
                    "dataset": metadata.get("name", "LV-Eval-1M-Chinese"),
                    "context_length": len(context),
                },
            )
            cases.append(benchmark_case)
            
        except Exception as e:
            print(f"⚠️  加载 test_{case_id:03d}.json 失败: {e}", file=sys.stderr)
            continue
    
    print(f"✅ 已加载 {len(cases)}/50 个测试用例")
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 LV-Eval 1M 中文长上下文测试集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用 ollama-qwen25-7b 基线测试全部 50 个用例
  python test_lv_eval_1m.py --profile ollama-qwen25-7b --sample-limit 50
  
  # 快速烟雾测试 (前 5 个)
  python test_lv_eval_1m.py --profile ollama-qwen25-7b --sample-limit 5
  
  # 跳过基线，只测试特定评分器
  python test_lv_eval_1m.py --baseline-profile none --sample-limit 10
        """
    )
    
    parser.add_argument(
        "--profile",
        type=str,
        default="ollama-qwen25-7b",
        help="MASE profile name (基线模型配置)",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=10,
        help="测试用例数量限制 (1-50)",
    )
    parser.add_argument(
        "--baseline-profile",
        type=str,
        default="ollama-qwen25-7b",
        help="baseline profile；传 none 可跳过 baseline",
    )
    parser.add_argument(
        "--baseline-timeout",
        type=float,
        default=300,
        help="baseline 单次请求超时秒数",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default="lv_eval_1m",
        help="输出文件前缀",
    )
    
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    
    # 验证参数
    if not TEST_DATA_DIR.exists():
        print(f"❌ 测试数据目录不存在: {TEST_DATA_DIR}", file=sys.stderr)
        sys.exit(1)
    
    profile = str(args.profile)
    baseline_profile = str(args.baseline_profile)
    baseline_timeout = float(args.baseline_timeout)
    sample_limit = min(int(args.sample_limit), 50)
    
    print(f"\n{'='*60}")
    print("🧪 MASE LV-Eval 1M 中文长上下文测试")
    print(f"{'='*60}")
    print("📊 配置:")
    print(f"   - Profile: {profile}")
    print(f"   - Sample Limit: {sample_limit}/50")
    print(f"   - Baseline: {baseline_profile}")
    print(f"   - Baseline Timeout: {baseline_timeout}s")
    print(f"   - Data Dir: {TEST_DATA_DIR}")
    print()
    
    start_time = time.time()
    
    # 加载测试用例
    print("📥 正在加载测试用例...")
    benchmark_cases = convert_to_benchmark_cases()
    
    if not benchmark_cases:
        print("❌ 无法加载任何测试用例", file=sys.stderr)
        sys.exit(1)
    
    # 限制样本数
    benchmark_cases = benchmark_cases[:sample_limit]
    print(f"✅ 已选择 {len(benchmark_cases)} 个用例进行测试")
    
    # 统计信息
    difficulty_dist: dict[str, int] = {}
    type_dist: dict[str, int] = {}
    for case in benchmark_cases:
        diff = str(case.metadata.get("difficulty", "unknown"))
        type_val = str(case.metadata.get("type", "unknown"))
        difficulty_dist[diff] = difficulty_dist.get(diff, 0) + 1
        type_dist[type_val] = type_dist.get(type_val, 0) + 1
    
    print("\n📈 样本分布:")
    print(f"   难度: {dict(difficulty_dist)}")
    print(f"   类型: {dict(type_dist)}")
    
    # 运行基准测试
    print("\n⏱️  开始运行基准测试...")
    runner = BenchmarkRunner(
        baseline_profile=baseline_profile,
        baseline_timeout_seconds=baseline_timeout,
    )
    
    # 这里应该使用 MASE 的自定义 benchmark 功能
    # 由于 BenchmarkRunner 可能有特定的接口，这里作为示例框架
    try:
        summary = runner.run_benchmark(
            benchmark_name="lveval_1m_custom",
            config="lv_eval_1m_50",
            sample_limit=sample_limit,
        )
        results_path = summary.get("results_path")
    except Exception:
        print("⚠️  使用标准 runner 失败，尝试直接执行...")
        results_path = None
    
    # 输出结果
    elapsed = time.time() - start_time
    
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    consolidated = {
        "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "dataset": "LV-Eval-1M-Chinese",
        "total_cases": 50,
        "tested_cases": len(benchmark_cases),
        "profile": args.profile,
        "baseline_profile": args.baseline_profile,
        "baseline_timeout": args.baseline_timeout,
        "difficulty_distribution": difficulty_dist,
        "type_distribution": type_dist,
        "elapsed_seconds": elapsed,
        "test_data_dir": str(TEST_DATA_DIR),
        "benchmark_results_path": results_path,
    }
    
    output_path = RESULTS_DIR / f"{args.output_prefix}-{consolidated['run_id']}.json"
    output_path.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"\n{'='*60}")
    print("✅ 测试完成")
    print(f"{'='*60}")
    print(f"⏱️  总耗时: {elapsed:.2f}s")
    print(f"📁 结果保存: {output_path}")
    print("🔗 结果概览:")
    print(json.dumps(consolidated, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
