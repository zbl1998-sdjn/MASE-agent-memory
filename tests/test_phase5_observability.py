from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase.metric_calculator import calculate_memory_metrics
from mase.phase5_evaluator import evaluate_memory_case
from mase.replay_engine import replay_trace_file
from mase.trace_recorder import record_trace_payload


def test_trace_recorder_and_replay_engine(tmp_path: Path, monkeypatch) -> None:
    trace_path = (tmp_path / "trace.jsonl").resolve()
    monkeypatch.setenv("MASE_TRACE_RECORD_PATH", str(trace_path))
    recorded = record_trace_payload(
        user_question="服务器端口是多少？",
        route={"action": "search_memory", "keywords": ["服务器端口"]},
        planner={"text": "facts-first"},
        thread={"thread_id": "t1"},
        executor_target={"mode": "grounded_answer"},
        answer="服务器端口是9909。",
        search_results=[{"_source": "entity_state", "freshness": "fresh"}],
        fact_sheet="[FACT] general_facts.服务器端口: 9909",
        evidence_assessment={"latency_ms": 12.0, "retrieval_plan": {"use_multipass": False}},
    )
    assert recorded == str(trace_path)
    replay = replay_trace_file(trace_path)
    assert replay["count"] == 1
    assert replay["metrics"]["current-state-hit"] == 1.0


def test_phase5_evaluator_and_metrics() -> None:
    row = evaluate_memory_case(
        expected="9909",
        actual="服务器端口是9909。",
        trace={"search_results": [{"_source": "entity_state", "freshness": "fresh"}]},
        problem_type="current_state",
    )
    metrics = calculate_memory_metrics(
        [
            {
                **row,
                "latency_ms": 20,
                "provenance_depth": 1,
            }
        ]
    )
    assert row["hit"] is True
    assert metrics["current-state-hit"] == 1.0
