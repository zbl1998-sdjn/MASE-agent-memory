from __future__ import annotations

import argparse
import json
import os
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from mase import MASESystem

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
MEMORY_RUNS_DIR = BASE_DIR / "memory_runs"

MEMORY_FACTS = [
    {
        "id": "gateway-port",
        "question": "请记住：我们演示环境的 API 网关暂时走 9909 端口，运维备注里还专门提醒不要和 9910 的灰度入口混淆。",
        "expected_fragments": ["9909"],
        "recall_questions": [
            "我们之前确认过的演示环境 API 网关端口到底是多少？",
            "把我们前面说过的演示网关端口再告诉我一次，我怕和灰度口记混了。",
        ],
    },
    {
        "id": "marketing-budget",
        "question": "请记住：Q3 的内容营销预算总额是 420 万元，其中短视频种草占 45%，效果广告占 35%，其余部分留给渠道试验。",
        "expected_fragments": ["420", "45%"],
        "recall_questions": [
            "我们前面聊到的 Q3 内容营销预算是多少，短视频种草占比又是多少？",
            "把之前记录的 Q3 营销预算结构复述一下，尤其是总额和短视频种草比例。",
        ],
    },
    {
        "id": "project-codename",
        "question": "请记住：这次仓储迁移项目内部代号叫“星河-7”，第一次切换窗口安排在 6 月 18 日下午四点到六点之间。",
        "expected_fragments": ["星河-7", "6月18"],
        "recall_questions": [
            "我们之前给仓储迁移项目起的内部代号是什么，首次切换窗口安排在哪天？",
            "把前面记录的仓储迁移项目代号和第一次切换时间再说一遍。",
        ],
    },
    {
        "id": "supplier",
        "question": "请记住：客服语音质检的外部供应商目前确定为澄音科技，合同里写的是首批交付 2000 条高风险样本。",
        "expected_fragments": ["澄音科技", "2000"],
        "recall_questions": [
            "我们早些时候敲定的客服语音质检供应商是谁，首批交付量是多少？",
            "把前面记录的语音质检供应商名称和首批样本数量告诉我。",
        ],
    },
    {
        "id": "meeting-room",
        "question": "请记住：下周二下午的跨部门复盘会改到 B-302 会议室举行，参会的核心角色是产品、投放和数据分析三组负责人。",
        "expected_fragments": ["B-302", "下周二"],
        "recall_questions": [
            "我们前面说的跨部门复盘会改到哪个会议室了，时间是在什么时候？",
            "把之前记录的复盘会地点和时间提醒我一下。",
        ],
    },
    {
        "id": "risk-threshold",
        "question": "请记住：风控侧把退款预警阈值先定在 7.5%，如果连续两天高于这个值，就要自动触发人工复审流程。",
        "expected_fragments": ["7.5%"],
        "recall_questions": [
            "我们刚才记录的退款预警阈值是多少，超过多久会触发人工复审？",
            "把前面说过的退款预警阈值再确认一下，我记得后面还有人工复审条件。",
        ],
    },
]

RELATED_FILLERS = [
    "如果一个 API 网关经常出现端口冲突，你会建议团队先检查哪三项配置，为什么？",
    "请用四句话解释为什么营销预算复盘不能只看总花费，还要同时看渠道上限和素材疲劳。",
    "如果仓储迁移项目要做灰度切换，你会优先监控哪两个指标来判断是否继续推进？",
    "站在客服质检的角度，首批样本如果数量不足，最可能带来什么评估偏差？",
    "请比较一下退款预警阈值设置得过高和过低，各自最容易引发什么业务问题。",
    "写一个 Python 函数，用来校验端口号是否在 1024 到 65535 的合法范围内。",
]

UNRELATED_FILLERS = [
    "请把“低延迟检索能提升回忆稳定性”改写成更适合周报的正式表述，控制在两句话以内。",
    "计算 (18 + 27) * 5 - 12 的结果，并用简洁的步骤说明你是怎么算出来的。",
    "如果一个团队要决定是用 webhook 还是轮询同步订单状态，你会怎么比较它们的适用场景？",
    "请用不超过五句话解释，为什么多人协作时接口命名规范比单人项目更重要。",
    "写一个简短的 SQL 查询，统计 orders 表里每个用户的订单数量，并按数量倒序排列。",
    "请把“先验证假设，再扩大投入”改写成更适合给老板看的汇报口吻。",
    "如果让你给新同学解释 RAG 和长上下文的区别，你会怎么讲得既直观又不失准确性？",
    "请用一个生活化的例子解释什么叫系统中的“单点故障”，不要太书面化。",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="随机化中长度回忆测试")
    parser.add_argument("--rounds", type=int, default=24, help="总轮数，不包含最终随机回忆题")
    parser.add_argument("--seed", type=int, default=20260410, help="随机种子，便于复现")
    parser.add_argument("--config", type=str, default=None, help="可选配置文件路径")
    return parser.parse_args()


def build_round_plan(rounds: int, rng: random.Random) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if rounds < len(MEMORY_FACTS) + 4:
        raise ValueError("rounds 太小，无法同时容纳记忆题和随机干扰题。")

    fact_rounds = sorted(rng.sample(range(1, rounds + 1), k=min(6, len(MEMORY_FACTS))))
    selected_facts = rng.sample(MEMORY_FACTS, k=len(fact_rounds))
    fact_by_round = dict(zip(fact_rounds, selected_facts, strict=True))

    plan: list[dict[str, Any]] = []
    inserted_facts: list[dict[str, Any]] = []
    for round_index in range(1, rounds + 1):
        if round_index in fact_by_round:
            fact = fact_by_round[round_index]
            inserted_facts.append({"round": round_index, **fact})
            plan.append(
                {
                    "round": round_index,
                    "type": "memory_fact",
                    "question": fact["question"],
                    "fact_id": fact["id"],
                }
            )
            continue

        filler_pool = RELATED_FILLERS if rng.random() < 0.45 else UNRELATED_FILLERS
        plan.append(
            {
                "round": round_index,
                "type": "filler",
                "question": rng.choice(filler_pool),
            }
        )

    selected_recall = rng.choice(inserted_facts)
    recall_question = rng.choice(selected_recall["recall_questions"])
    return plan, {"target": selected_recall, "question": recall_question}


def evaluate_answer(answer: str, expected_fragments: list[str]) -> dict[str, Any]:
    checks = {fragment: fragment in answer for fragment in expected_fragments}
    return {
        "all_matched": all(checks.values()),
        "fragment_checks": checks,
    }


def run_randomized_recall(
    rounds: int,
    seed: int,
    config: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    rng = random.Random(seed)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    memory_dir = MEMORY_RUNS_DIR / f"randomized-recall-{run_id}"
    results_path = RESULTS_DIR / f"randomized-recall-{run_id}.json"

    if memory_dir.exists():
        shutil.rmtree(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    previous_memory_dir = os.environ.get("MASE_MEMORY_DIR")
    os.environ["MASE_MEMORY_DIR"] = str(memory_dir.resolve())
    try:
        system = MASESystem(config)
        round_plan, recall_plan = build_round_plan(rounds, rng)
        round_results: list[dict[str, Any]] = []

        for item in round_plan:
            trace = system.run_with_trace(item["question"], log=False)
            round_results.append(
                {
                    "round": item["round"],
                    "type": item["type"],
                    "fact_id": item.get("fact_id"),
                    "question": item["question"],
                    "route": {
                        "action": trace.route.action,
                        "keywords": trace.route.keywords,
                    },
                    "task_type": trace.plan.task_type,
                    "executor_mode": trace.plan.executor_mode,
                    "use_memory": trace.plan.use_memory,
                    "thread": trace.thread.to_dict(),
                    "executor_target": trace.executor_target,
                    "answer_preview": trace.answer[:180],
                    "record_path": trace.record_path,
                }
            )

        recall_trace = system.run_with_trace(recall_plan["question"], log=False)
        evaluation = evaluate_answer(
            recall_trace.answer,
            recall_plan["target"]["expected_fragments"],
        )

        false_positive_examples = [
            {
                "round": item["round"],
                "question": item["question"],
                "keywords": item["route"]["keywords"],
                "task_type": item["task_type"],
            }
            for item in round_results
            if item["type"] == "filler" and item["route"]["action"] == "search_memory"
        ]

        summary = {
            "run_id": run_id,
            "seed": seed,
            "config": str(config) if config else "default",
            "memory_dir": str(memory_dir),
            "results_path": str(results_path) if persist else None,
            "round_count_before_recall": rounds,
            "round_plan": round_results,
            "recall_test": {
                "target_fact_id": recall_plan["target"]["id"],
                "target_round": recall_plan["target"]["round"],
                "target_original_question": recall_plan["target"]["question"],
                "recall_question": recall_plan["question"],
                "expected_fragments": recall_plan["target"]["expected_fragments"],
                "route": {
                    "action": recall_trace.route.action,
                    "keywords": recall_trace.route.keywords,
                },
                "task_type": recall_trace.plan.task_type,
                "executor_mode": recall_trace.plan.executor_mode,
                "use_memory": recall_trace.plan.use_memory,
                "thread": recall_trace.thread.to_dict(),
                "executor_target": recall_trace.executor_target,
                "fact_sheet_preview": recall_trace.fact_sheet[:300],
                "answer": recall_trace.answer,
                "evaluation": evaluation,
            },
            "checks": {
                "memory_rounds_inserted": sum(1 for item in round_results if item["type"] == "memory_fact"),
                "filler_rounds": sum(1 for item in round_results if item["type"] == "filler"),
                "false_positive_search_memory_count": len(false_positive_examples),
                "recall_used_memory": recall_trace.plan.use_memory,
                "recall_route_search_memory": recall_trace.route.action == "search_memory",
                "recall_answer_matched": evaluation["all_matched"],
            },
            "false_positive_examples": false_positive_examples[:6],
        }

        if persist:
            results_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    finally:
        if previous_memory_dir is None:
            os.environ.pop("MASE_MEMORY_DIR", None)
        else:
            os.environ["MASE_MEMORY_DIR"] = previous_memory_dir


def main() -> None:
    args = parse_args()
    summary = run_randomized_recall(
        rounds=args.rounds,
        seed=args.seed,
        config=args.config,
        persist=True,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
