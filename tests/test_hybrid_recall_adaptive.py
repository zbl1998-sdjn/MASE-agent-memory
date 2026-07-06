"""HybridReranker 查询自适应权重:先钉默认行为,再验证 opt-in 行为。

特征测试(钉死):不开 ``MASE_HYBRID_RECALL_ADAPTIVE`` 时,时间线索查询与
普通查询使用完全相同的固定权重,components 形状不变——自适应特性落地后
默认路径必须逐字节保持这些断言。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mase.hybrid_recall import HybridReranker  # noqa: E402

_NOW = datetime(2026, 7, 6, 12, 0, 0)


def _candidates() -> list[dict]:
    return [
        {"id": "old", "text": "budget meeting notes", "score": 0.9,
         "timestamp": (_NOW - timedelta(days=200)).isoformat()},
        {"id": "new", "text": "budget meeting notes", "score": 0.5,
         "timestamp": (_NOW - timedelta(days=1)).isoformat()},
    ]


def test_default_weights_identical_for_temporal_and_plain_queries(monkeypatch) -> None:
    monkeypatch.delenv("MASE_HYBRID_RECALL_ADAPTIVE", raising=False)
    monkeypatch.delenv("MASE_HYBRID_RECALL_WEIGHTS", raising=False)
    reranker = HybridReranker()
    plain = reranker.rerank("budget meeting", _candidates(), query_time=_NOW)
    temporal = reranker.rerank("what did we discuss yesterday?", _candidates(), query_time=_NOW)
    expected = {"alpha": 0.5, "beta": 0.3, "gamma": 0.2}
    assert plain[0]["hybrid_components"]["weights"] == expected
    assert temporal[0]["hybrid_components"]["weights"] == expected


def test_default_components_shape_is_stable(monkeypatch) -> None:
    monkeypatch.delenv("MASE_HYBRID_RECALL_ADAPTIVE", raising=False)
    out = HybridReranker().rerank("what did we discuss yesterday?", _candidates(), query_time=_NOW)
    assert set(out[0]["hybrid_components"].keys()) == {"dense", "bm25", "temporal", "weights"}
