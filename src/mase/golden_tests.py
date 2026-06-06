"""长期记忆黄金用例执行器，用于把召回质量接入发布门禁。"""
from __future__ import annotations

from typing import Any

from mase.synthetic_replay import MemorySearch, evaluate_replay_case

# 默认用例故意不绑定具体用户事实，只钉住“有作用域”和“不能跨域泄漏”。
DEFAULT_GOLDEN_CASES: list[dict[str, Any]] = [
    {
        "case_id": "current-fact-recall",
        "category": "current_fact",
        "severity": "critical",
        "query": "project owner",
        "expected_terms": [],
        "forbidden_terms": [],
    },
    {
        "case_id": "scope-isolation",
        "category": "scope_safety",
        "severity": "critical",
        "query": "private workspace memory",
        "expected_terms": [],
        "forbidden_terms": ["other-tenant", "cross-scope"],
    },
]


def _score_case(result: dict[str, Any], case: dict[str, Any]) -> float:
    """组合期望命中、禁止词隔离和召回命中率，得到 0-1 质量分。"""
    expected_count = len(result["expected_terms"])
    expected_score = 1.0
    if expected_count:
        expected_score = len(result["found_expected_terms"]) / expected_count
    forbidden_score = 0.0 if result["found_forbidden_terms"] else 1.0
    hit_score = 1.0 if result["hit_count"] > 0 or not result["expected_terms"] else 0.0
    required_quality = float(case.get("min_quality_score") or 0.0)
    base_score = round((expected_score * 0.55) + (forbidden_score * 0.35) + (hit_score * 0.10), 3)
    return base_score if base_score >= required_quality else min(base_score, required_quality - 0.001)


def _verdict(result: dict[str, Any], case: dict[str, Any], score: float) -> str:
    """同时满足 replay 状态和用例阈值才算通过。"""
    threshold = float(case.get("min_quality_score") or 0.8)
    if result["status"] == "passed" and score >= threshold:
        return "passed"
    return "failed"


def run_golden_tests(
    memory: MemorySearch,
    cases: list[dict[str, Any]] | None,
    *,
    scope: dict[str, Any],
    default_top_k: int = 5,
) -> dict[str, Any]:
    """运行黄金用例并输出 release_gate，供 CI 或人工验收读取。"""
    selected_cases = cases if cases is not None else DEFAULT_GOLDEN_CASES
    results: list[dict[str, Any]] = []
    for case in selected_cases:
        replay_result = evaluate_replay_case(memory, case, scope=scope, default_top_k=default_top_k)
        quality_score = _score_case(replay_result, case)
        verdict = _verdict(replay_result, case, quality_score)
        results.append(
            {
                **replay_result,
                "category": str(case.get("category") or "custom"),
                "severity": str(case.get("severity") or "normal"),
                "quality_score": quality_score,
                "min_quality_score": float(case.get("min_quality_score") or 0.8),
                "verdict": verdict,
            }
        )
    failed = [result for result in results if result["verdict"] != "passed"]
    critical_failed = [result for result in failed if result["severity"] == "critical"]
    return {
        "scope": scope,
        "summary": {
            "case_count": len(results),
            "passed_count": len(results) - len(failed),
            "failed_count": len(failed),
            "critical_failed_count": len(critical_failed),
            "pass_rate": round((len(results) - len(failed)) / max(1, len(results)), 3),
            "release_gate": "blocked" if critical_failed else ("warning" if failed else "passed"),
        },
        "results": results,
    }


__all__ = ["DEFAULT_GOLDEN_CASES", "run_golden_tests"]
