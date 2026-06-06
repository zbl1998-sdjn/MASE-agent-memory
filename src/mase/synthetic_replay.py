"""用合成 case 驱动记忆搜索接口，验证召回与作用域隔离。"""
from __future__ import annotations

import re
from typing import Any, Protocol


class MemorySearch(Protocol):
    """replay 所需的最小记忆搜索协议。"""

    def search_memory(
        self,
        keywords: list[str],
        *,
        full_query: str | None = None,
        limit: int = 5,
        include_history: bool = False,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ...


def _keywords(query: str) -> list[str]:
    """从查询中提取搜索词；空结果时回退到完整查询。"""
    return re.findall(r"[\w-]{2,}", query) or [query]


def _row_text(row: dict[str, Any]) -> str:
    """把召回行中可供断言的文本字段拼接成检索文本。"""
    keys = ("content", "entity_key", "entity_value", "category", "answer_preview", "user_question")
    return " ".join(str(row.get(key) or "") for key in keys).lower()


def _contains_any(rows: list[dict[str, Any]], terms: list[str]) -> list[str]:
    """返回在召回结果中实际出现的期望词或禁止词。"""
    haystack = "\n".join(_row_text(row) for row in rows)
    return [term for term in terms if term.lower() in haystack]


def evaluate_replay_case(
    memory: MemorySearch,
    case: dict[str, Any],
    *,
    scope: dict[str, Any],
    default_top_k: int = 5,
) -> dict[str, Any]:
    """执行单条 replay case，记录命中、缺失和越权词样本。"""
    query = str(case.get("query") or "").strip()
    expected_terms = [str(term) for term in case.get("expected_terms") or [] if str(term).strip()]
    forbidden_terms = [str(term) for term in case.get("forbidden_terms") or [] if str(term).strip()]
    top_k = int(case.get("top_k") or default_top_k)
    hits = memory.search_memory(
        _keywords(query),
        full_query=query,
        limit=top_k,
        include_history=True,
        scope_filters=scope,
    )
    found_expected = _contains_any(hits, expected_terms)
    found_forbidden = _contains_any(hits, forbidden_terms)
    missing_expected = [term for term in expected_terms if term not in found_expected]
    status = "passed" if not missing_expected and not found_forbidden else "failed"
    return {
        "case_id": str(case.get("case_id") or query),
        "query": query,
        "status": status,
        "hit_count": len(hits),
        "expected_terms": expected_terms,
        "found_expected_terms": found_expected,
        "missing_expected_terms": missing_expected,
        "forbidden_terms": forbidden_terms,
        "found_forbidden_terms": found_forbidden,
        "sample_hits": hits[: min(3, len(hits))],
    }


def run_synthetic_replay(
    memory: MemorySearch,
    cases: list[dict[str, Any]],
    *,
    scope: dict[str, Any],
    default_top_k: int = 5,
) -> dict[str, Any]:
    """批量运行 replay case，并输出 pass_rate 汇总。"""
    results = [evaluate_replay_case(memory, case, scope=scope, default_top_k=default_top_k) for case in cases]
    failed = [result for result in results if result["status"] != "passed"]
    return {
        "scope": scope,
        "summary": {
            "case_count": len(results),
            "passed_count": len(results) - len(failed),
            "failed_count": len(failed),
            "pass_rate": round((len(results) - len(failed)) / max(1, len(results)), 3),
        },
        "results": results,
    }


__all__ = ["evaluate_replay_case", "run_synthetic_replay"]
