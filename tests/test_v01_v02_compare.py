from __future__ import annotations

import importlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
MEMORY_ROOT = BASE_DIR / "memory_runs"
RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")


def reload_modules(memory_dir: Path):
    os.environ["MASE_MEMORY_DIR"] = str(memory_dir)
    import tools

    import mase

    tools = importlib.reload(tools)
    mase = importlib.reload(mase)
    return tools, mase


def write_seed_records(memory_dir: Path, records: list[dict[str, str]]) -> None:
    tools, _ = reload_modules(memory_dir)
    for record in records:
        tools.write_interaction(
            record["user_query"],
            record["assistant_response"],
            record["summary"],
        )


def search_memory_v01(memory_dir: Path, keywords: list[str], limit: int = 1) -> list[dict[str, Any]]:
    tools, _ = reload_modules(memory_dir)
    expanded = tools._expand_keywords(keywords)
    results: list[dict[str, Any]] = []

    def old_priority(record: dict[str, Any]) -> int:
        user_query = str(record.get("user_query", ""))
        assistant_response = str(record.get("assistant_response", ""))
        semantic_summary = str(record.get("semantic_summary", ""))
        priority = 0
        if any(marker in user_query for marker in tools.MEMORY_WRITE_MARKERS):
            priority += 100
        for keyword in expanded:
            lowered = keyword.lower()
            if lowered in user_query.lower():
                priority += 10
            if lowered in semantic_summary.lower():
                priority += 6
            if lowered in assistant_response.lower():
                priority += 4
        return priority

    for filepath in tools._candidate_files(None):
        record = tools.load_record(filepath)
        searchable_text = " ".join(
            [
                str(record.get("user_query", "")),
                str(record.get("assistant_response", "")),
                str(record.get("semantic_summary", "")),
            ]
        )
        if any(keyword.lower() in searchable_text.lower() for keyword in expanded):
            date_value, time_value = tools._extract_date_and_time(filepath, record)
            results.append(
                {
                    "date": date_value,
                    "time": time_value,
                    "summary": record.get("semantic_summary", ""),
                    "user_query": record.get("user_query", ""),
                    "assistant_response": record.get("assistant_response", ""),
                    "filepath": str(filepath),
                    "_priority": old_priority(record),
                }
            )

    results.sort(key=lambda item: -item["_priority"])
    trimmed = results[:limit]
    for item in trimmed:
        item.pop("_priority", None)
    return trimmed


def route_v01(question: str) -> dict[str, Any]:
    question = question.strip()
    if any(marker in question for marker in ["请记住", "记住：", "记一下"]):
        return {
            "action": "direct_answer",
            "keywords": [],
            "reasoning": "提供新信息，直接回答。",
        }
    if any(marker in question for marker in ["之前聊", "上次", "我刚才说", "最开始聊", "还记得"]):
        keywords = []
        for term in ["项目代号", "截止日期", "服务器端口", "端口", "Q3预算", "营销预算", "预算", "线上投放"]:
            if term in question:
                keywords.append(term)
        if not keywords:
            keywords = [question[:12]]
        return {
            "action": "search_memory",
            "keywords": keywords,
            "reasoning": "指向历史内容，查询记忆。",
        }
    return {
        "action": "direct_answer",
        "keywords": [],
        "reasoning": "默认直接回答。",
    }


def build_fact_sheet(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    return "\n".join(
        [
            "\n".join(
                [
                    f"- 时间：{item['date']} {item['time']}",
                    f"  用户原话：{item['user_query']}",
                    f"  记录摘要：{item['summary']}",
                    f"  已存回答：{item['assistant_response']}",
                ]
            )
            for item in records
        ]
    )


def run_scenario_v01(name: str, seed_records: list[dict[str, str]], question: str, expected: str) -> dict[str, Any]:
    memory_dir = MEMORY_ROOT / f"{RUN_ID}-{name}-v01"
    memory_dir.mkdir(parents=True, exist_ok=True)
    write_seed_records(memory_dir, seed_records)
    _, mase = reload_modules(memory_dir)

    route = route_v01(question)
    if route["action"] == "search_memory":
        records = search_memory_v01(memory_dir, route["keywords"], limit=1)
        fact_sheet = build_fact_sheet(records)
        answer = mase.call_executor(question, fact_sheet, allow_general_knowledge=False)
    else:
        records = []
        answer = mase.call_executor(question, "", allow_general_knowledge=True)

    return {
        "route": route,
        "records": records,
        "answer": answer,
        "success": expected in answer,
    }


def run_scenario_v02(name: str, seed_records: list[dict[str, str]], question: str, expected: str) -> dict[str, Any]:
    memory_dir = MEMORY_ROOT / f"{RUN_ID}-{name}-v02"
    memory_dir.mkdir(parents=True, exist_ok=True)
    write_seed_records(memory_dir, seed_records)
    tools, mase = reload_modules(memory_dir)

    route = mase.call_router(question)
    if route["action"] == "search_memory":
        records = tools.search_memory(route["keywords"], limit=1)
        fact_sheet = tools.format_fact_sheet(records)
        answer = mase.call_executor(question, fact_sheet, allow_general_knowledge=False)
    else:
        records = []
        answer = mase.call_executor(question, "", allow_general_knowledge=True)

    return {
        "route": route,
        "records": records,
        "answer": answer,
        "success": expected in answer,
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)

    scenarios = {
        "long_range_budget": {
            "seed_records": [
                {
                    "user_query": "请记住：我们Q3营销预算是350万元，线上投放占60%，合作平台是字节跳动和腾讯。",
                    "assistant_response": "已记住：Q3营销预算350万元，线上投放占60%，合作平台是字节跳动和腾讯。",
                    "summary": "Q3预算350万元，线上投放占60%，合作平台为字节跳动和腾讯。",
                }
            ]
            + [
                {
                    "user_query": f"闲聊第{index}轮：今天天气不错。",
                    "assistant_response": f"收到，这是第{index}轮记录。",
                    "summary": f"闲聊第{index}轮记录。",
                }
                for index in range(2, 30)
            ],
            "question": "我们最开始聊的那个Q3预算，线上投放比例是多少？",
            "expected": "60%",
        },
        "ambiguous_recent_reference": {
            "seed_records": [
                {
                    "user_query": "请记住：我的项目代号是蓝海，截止日期是4月30日。",
                    "assistant_response": "好的，我已经记住了您的信息。您的项目代号是蓝海，截止日期是4月30日。",
                    "summary": "用户的项目代号为蓝海，截止日期为4月30日。",
                }
            ]
            + [
                {
                    "user_query": f"闲聊第{index}轮：记录一下普通事项。",
                    "assistant_response": f"收到，这是第{index}轮记录。",
                    "summary": f"闲聊第{index}轮记录。",
                }
                for index in range(2, 15)
            ]
            + [
                {
                    "user_query": "请记住：我的项目代号是星河，截止日期是5月15日。",
                    "assistant_response": "好的，我已经记住了您的信息。您的项目代号是星河，截止日期是5月15日。",
                    "summary": "好的，“星河”项目截止日期为5月15日。",
                }
            ]
            + [
                {
                    "user_query": f"闲聊第{index}轮：继续处理普通事项。",
                    "assistant_response": f"收到，这是第{index}轮记录。",
                    "summary": f"闲聊第{index}轮记录。",
                }
                for index in range(16, 30)
            ],
            "question": "我刚才说的项目代号是什么？",
            "expected": "星河",
        },
    }

    comparisons: dict[str, Any] = {}
    for name, scenario in scenarios.items():
        comparisons[name] = {
            "v0_1": run_scenario_v01(name, scenario["seed_records"], scenario["question"], scenario["expected"]),
            "v0_2": run_scenario_v02(name, scenario["seed_records"], scenario["question"], scenario["expected"]),
        }

    summary = {
        "run_id": RUN_ID,
        "version_reference": {
            "v0_1": "stateful-router-reference-emulation",
            "v0_2": "stateless-router-with-time-decay",
        },
        "comparisons": comparisons,
        "scoreboard": {
            "v0_1_success_count": sum(1 for item in comparisons.values() if item["v0_1"]["success"]),
            "v0_2_success_count": sum(1 for item in comparisons.values() if item["v0_2"]["success"]),
            "scenario_count": len(comparisons),
        },
    }

    output_path = RESULTS_DIR / f"mase-v01-v02-compare-{RUN_ID}.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
