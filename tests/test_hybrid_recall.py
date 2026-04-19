from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mase.hybrid_recall import HybridReranker  # noqa: E402


def test_bm25_ranks_lexical_overlap_higher():
    candidates = [
        {"id": "a", "text": "the cat sat on the mat", "score": 0.5},
        {"id": "b", "text": "quantum chromodynamics is complicated", "score": 0.5},
        {"id": "c", "text": "an unrelated note about gardening", "score": 0.5},
    ]
    reranker = HybridReranker(alpha=0.0, beta=1.0, gamma=0.0)
    out = reranker.rerank("cat mat", candidates)
    assert out[0]["id"] == "a", f"expected lexical overlap to win, got {[c['id'] for c in out]}"


def test_temporal_cue_boosts_recent():
    now = datetime(2025, 1, 10, 12, 0, 0)
    yesterday = now - timedelta(days=1)
    long_ago = now - timedelta(days=200)
    candidates = [
        {"id": "old", "text": "meeting notes", "score": 0.6, "timestamp": long_ago.isoformat()},
        {"id": "new", "text": "meeting notes", "score": 0.5, "timestamp": yesterday.isoformat()},
    ]
    reranker = HybridReranker(alpha=0.2, beta=0.0, gamma=0.8)
    out = reranker.rerank("what did we discuss yesterday?", candidates, query_time=now)
    assert out[0]["id"] == "new", f"expected recent doc to win with temporal cue, got {[c['id'] for c in out]}"


def test_dense_only_fallback_preserves_order():
    candidates = [
        {"id": "x", "text": "alpha", "score": 0.9},
        {"id": "y", "text": "bravo", "score": 0.6},
        {"id": "z", "text": "charlie", "score": 0.3},
    ]
    reranker = HybridReranker(alpha=1.0, beta=0.0, gamma=0.0)
    out = reranker.rerank("zzz_no_overlap", candidates)
    assert [c["id"] for c in out] == ["x", "y", "z"]


def test_empty_candidates_returns_empty():
    assert HybridReranker().rerank("anything", []) == []


def test_does_not_mutate_input():
    cand = [{"id": "a", "text": "hello world", "score": 0.5}]
    snapshot = {k: v for k, v in cand[0].items()}
    HybridReranker().rerank("hello", cand)
    assert cand[0] == snapshot


def test_env_weight_override(monkeypatch):
    monkeypatch.setenv("MASE_HYBRID_RECALL_WEIGHTS", "0.1,0.8,0.1")
    r = HybridReranker()
    assert (r.alpha, r.beta, r.gamma) == (0.1, 0.8, 0.1)


def test_hybrid_score_attached():
    cand = [{"id": "a", "text": "hi", "score": 0.5}]
    out = HybridReranker().rerank("hi", cand)
    assert "hybrid_score" in out[0]
    assert "hybrid_components" in out[0]
