from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mase import ROUTER_SYSTEM, probe_router

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"

SEARCH_QUERY = "我们上次讨论的那个Q3预算，线上投放比例是多少？"
DIRECT_QUERY = "什么是向量数据库？"


def build_long_system_prompt(target_chars: int) -> str:
    example_block = """
示例输入：我们上次讨论的部署方案还记得吗？
示例输出：{"action":"search_memory","reasoning":"问题显式指向过去讨论的方案。","keywords":["部署方案"],"date_hint":null}

示例输入：明天天气怎么样？
示例输出：{"action":"direct_answer","reasoning":"这是实时信息问题。","keywords":[],"date_hint":null}

示例输入：请记住：服务器端口设为8765。
示例输出：{"action":"direct_answer","reasoning":"这是在提供新信息让系统记住。","keywords":[],"date_hint":null}
"""
    prompt = ROUTER_SYSTEM
    while len(prompt) < target_chars:
        prompt += "\n" + example_block
    return prompt[:target_chars]


def has_chinese_keywords(route: dict[str, Any] | None) -> bool:
    if route is None:
        return False
    keywords = route.get("keywords", [])
    if not isinstance(keywords, list):
        return False
    for keyword in keywords:
        text = str(keyword)
        if not any("\u4e00" <= char <= "\u9fff" for char in text):
            return False
    return True


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    targets = [4_000, 8_000, 12_000, 16_000, 20_000, 24_000, 28_000, 32_000]
    records: list[dict[str, Any]] = []

    for target in targets:
        system_prompt = build_long_system_prompt(target)
        search_probe = probe_router(SEARCH_QUERY, system_prompt=system_prompt, apply_heuristic=False)
        direct_probe = probe_router(DIRECT_QUERY, system_prompt=system_prompt, apply_heuristic=False)

        search_route = search_probe["route"]
        direct_route = direct_probe["route"]

        record = {
            "target_chars": target,
            "actual_chars": len(system_prompt),
            "search_probe": {
                "route": search_route,
                "parse_error": search_probe["parse_error"],
                "raw_preview": str(search_probe["raw_content"])[:200],
                "json_valid": search_probe["parse_error"] is None,
                "action_correct": isinstance(search_route, dict) and search_route.get("action") == "search_memory",
                "keywords_are_chinese": has_chinese_keywords(search_route if isinstance(search_route, dict) else None),
            },
            "direct_probe": {
                "route": direct_route,
                "parse_error": direct_probe["parse_error"],
                "raw_preview": str(direct_probe["raw_content"])[:200],
                "json_valid": direct_probe["parse_error"] is None,
                "action_correct": isinstance(direct_route, dict) and direct_route.get("action") == "direct_answer",
            },
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False, indent=2))

    first_failure: int | None = None
    success_chars: list[int] = []
    for item in records:
        passed = (
            item["search_probe"]["json_valid"]
            and item["search_probe"]["action_correct"]
            and item["search_probe"]["keywords_are_chinese"]
            and item["direct_probe"]["json_valid"]
            and item["direct_probe"]["action_correct"]
        )
        if passed:
            success_chars.append(int(item["actual_chars"]))
            continue
        if first_failure is None:
            first_failure = int(item["actual_chars"])

    summary = {
        "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "results": records,
        "first_failure_chars": first_failure,
        "max_success_chars": max(success_chars) if success_chars else None,
    }

    output_path = RESULTS_DIR / f"router-context-limit-{summary['run_id']}.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 路由上下文极限测试汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
