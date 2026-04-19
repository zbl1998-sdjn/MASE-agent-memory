from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")
MEMORY_ROOT = BASE_DIR / "memory_runs"
RESULTS_DIR = BASE_DIR / "results"
MEMORY_DIR = MEMORY_ROOT / f"mase-100-{RUN_ID}"

os.environ["MASE_MEMORY_DIR"] = str(MEMORY_DIR)

from mase_tools.legacy import search_memory

from mase import call_router, mase_ask

TARGET_FACT = "我们Q3营销预算是350万元，线上投放占60%，合作平台是字节跳动和腾讯。"
FINAL_QUESTION = "我们最开始聊的那个Q3预算，线上投放比例是多少？"


def list_json_files() -> list[Path]:
    if not MEMORY_DIR.exists():
        return []
    return sorted(MEMORY_DIR.rglob("*.json"))


def filler_question(index: int) -> str:
    return f"闲聊第{index}轮：请简单回复“收到，这是第{index}轮记录”。"


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    questions = [f"请记住：{TARGET_FACT}"]
    questions.extend(filler_question(index) for index in range(2, 100))
    questions.append(FINAL_QUESTION)

    round_results: list[dict[str, object]] = []
    output_path = RESULTS_DIR / f"mase-100-rounds-{RUN_ID}.json"

    try:
        for index, question in enumerate(questions, start=1):
            before_count = len(list_json_files())
            answer = mase_ask(question, log=False)
            after_count = len(list_json_files())
            round_results.append(
                {
                    "round": index,
                    "question": question,
                    "answer_preview": answer[:120],
                    "json_delta": after_count - before_count,
                }
            )
            print(f"[{index:03d}/100] json_delta={after_count - before_count} answer={answer[:60]}")

        error = None
    except Exception as exc:
        error = str(exc)

    route = call_router(FINAL_QUESTION)
    recall_results = search_memory(route.get("keywords", []), route.get("date_hint"), limit=3)
    memory_files = list_json_files()
    elapsed_seconds = round(time.time() - start_time, 2)
    final_answer = round_results[-1]["answer_preview"] if round_results else ""

    summary = {
        "run_id": RUN_ID,
        "memory_dir": str(MEMORY_DIR),
        "results_file": str(output_path),
        "round_count": len(questions),
        "completed_rounds": len(round_results),
        "json_file_count": len(memory_files),
        "elapsed_seconds": elapsed_seconds,
        "target_fact": TARGET_FACT,
        "final_question": FINAL_QUESTION,
        "final_route": route,
        "final_answer": final_answer,
        "search_result_count": len(recall_results),
        "search_results": recall_results,
        "error": error,
        "checks": {
            "completed_all_rounds": error is None and len(round_results) == 100,
            "route_is_search_memory": route.get("action") == "search_memory",
            "json_generated_every_round": all(item["json_delta"] == 1 for item in round_results),
            "json_file_count_is_100": len(memory_files) == 100,
            "answer_mentions_60": "60" in str(final_answer),
            "answer_mentions_60_percent": "60%" in str(final_answer),
            "first_record_found": any("350万元" in item.get("user_query", "") for item in recall_results),
        },
        "round_results_tail": round_results[-5:],
    }

    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== MASE 100轮压测结果 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if error is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
