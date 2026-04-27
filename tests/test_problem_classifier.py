from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase.problem_classifier import ProblemClassifier, build_retrieval_plan


def test_problem_classifier_detects_current_state() -> None:
    result = ProblemClassifier().classify("服务器端口现在是多少？", route_keywords=["服务器端口"])
    assert result.problem_type == "current_state"


def test_problem_classifier_detects_temporal_question() -> None:
    result = ProblemClassifier().classify("上周之前那个预算是多少？", route_keywords=["预算"])
    assert result.problem_type == "temporal"


def test_problem_classifier_detects_update_question() -> None:
    result = ProblemClassifier().classify("我之前把预算改成多少来着？", route_keywords=["预算"])
    assert result.problem_type == "update"


def test_retrieval_plan_enables_history_for_update_questions() -> None:
    plan = build_retrieval_plan("我之前把预算改成多少来着？", route_keywords=["预算"], base_limit=5)
    assert plan.include_history is True
    assert plan.search_limit >= 8


def test_retrieval_plan_widens_aggregate_queries() -> None:
    plan = build_retrieval_plan("我们之前一共调整过多少次预算？", route_keywords=["预算"], base_limit=5)
    assert plan.classification.problem_type == "aggregate"
    assert plan.use_hybrid_rerank is True
    assert plan.search_limit >= 10
