"""Hybrid recall reranker (BM25 + dense + temporal-aware).

Pluggable, pure-function module. Activated only when the env flag
``MASE_HYBRID_RECALL=1`` is set by the caller. This module performs no I/O
and makes no model calls — it is safe to import unconditionally.

Final score (per candidate):
    score = α * dense + β * bm25 + γ * temporal

Defaults: α=0.5, β=0.3, γ=0.2. Override via env
``MASE_HYBRID_RECALL_WEIGHTS="0.5,0.3,0.2"``.
"""
from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

try:  # Optional dependency — fall back to inline BM25 if missing.
    from rank_bm25 import BM25Okapi  # type: ignore
    _HAS_RANK_BM25 = True
except Exception:  # pragma: no cover - exercised only when lib missing
    _HAS_RANK_BM25 = False


_TEMPORAL_CUES_RECENT = (
    "yesterday", "today", "last night", "this morning", "recently",
    "just now", "a moment ago", "earlier today",
    "昨天", "今天", "刚才", "刚刚", "最近", "今早", "今晚",
)
_TEMPORAL_CUES_WEEK = (
    "last week", "this week", "past week", "few days ago",
    "上周", "本周", "这周", "前几天", "几天前",
)
_TEMPORAL_CUES_MONTH = (
    "last month", "this month", "weeks ago",
    "上个月", "本月", "这个月", "几周前",
)
_TEMPORAL_CUES_GENERIC = (
    "before", "previously", "earlier", "ago",
    "之前", "以前", "我上次", "上次", "过去",
)

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    text = text.lower()
    tokens = _TOKEN_RE.findall(text)
    # Add CJK character unigrams for non-whitespace languages.
    cjk = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    return tokens + cjk


def _detect_temporal_window(query: str) -> tuple[str | None, timedelta | None]:
    """Return (cue_kind, target_window). cue_kind is None when no cue."""
    if not query:
        return None, None
    q = query.lower()
    for cue in _TEMPORAL_CUES_RECENT:
        if cue in q:
            return "recent", timedelta(days=2)
    for cue in _TEMPORAL_CUES_WEEK:
        if cue in q:
            return "week", timedelta(days=7)
    for cue in _TEMPORAL_CUES_MONTH:
        if cue in q:
            return "month", timedelta(days=31)
    for cue in _TEMPORAL_CUES_GENERIC:
        if cue in q:
            return "generic", timedelta(days=30)
    return None, None


def _coerce_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value))
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Try ISO8601 first.
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def _minmax_normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-12:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


# ---------------------------------------------------------------------------
# Inline BM25 fallback (used only when rank_bm25 is not installed).
# ---------------------------------------------------------------------------
class _InlineBM25:
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.doc_len = [len(d) for d in corpus]
        self.avgdl = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.df: dict[str, int] = {}
        self.tf: list[dict[str, int]] = []
        for doc in corpus:
            seen: dict[str, int] = {}
            for tok in doc:
                seen[tok] = seen.get(tok, 0) + 1
            self.tf.append(seen)
            for tok in seen:
                self.df[tok] = self.df.get(tok, 0) + 1
        self.N = len(corpus)
        self.idf: dict[str, float] = {
            tok: math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            for tok, df in self.df.items()
        }

    def get_scores(self, query: Iterable[str]) -> list[float]:
        scores = [0.0] * self.N
        if self.avgdl == 0:
            return scores
        for q in query:
            idf = self.idf.get(q)
            if idf is None:
                continue
            for i, tf_doc in enumerate(self.tf):
                f = tf_doc.get(q)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                scores[i] += idf * (f * (self.k1 + 1)) / denom
        return scores


def _bm25_scores(query_tokens: list[str], doc_token_lists: list[list[str]]) -> list[float]:
    if not doc_token_lists:
        return []
    if _HAS_RANK_BM25:
        try:
            bm25 = BM25Okapi(doc_token_lists)
            return list(bm25.get_scores(query_tokens))
        except Exception:
            pass
    return _InlineBM25(doc_token_lists).get_scores(query_tokens)


def _temporal_score(
    cand_ts: datetime | None,
    query_time: datetime | None,
    target_window: timedelta | None,
) -> float:
    if cand_ts is None or query_time is None:
        return 0.0
    delta = abs((query_time - cand_ts).total_seconds())
    if target_window is not None:
        # Boost candidates whose timestamp lies inside the cued window;
        # exponential decay outside it.
        window_s = max(target_window.total_seconds(), 1.0)
        if delta <= window_s:
            return 1.0
        return math.exp(-(delta - window_s) / window_s)
    # No cue: gentle recency decay (half-life ~30d).
    half_life = 30 * 24 * 3600.0
    return math.exp(-delta / half_life) * 0.5


def _load_weights() -> tuple[float, float, float]:
    raw = os.environ.get("MASE_HYBRID_RECALL_WEIGHTS")
    if not raw:
        return 0.5, 0.3, 0.2
    try:
        parts = [float(x) for x in raw.split(",")]
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
    except ValueError:
        pass
    return 0.5, 0.3, 0.2


class HybridReranker:
    """BM25 + dense + temporal-aware reranker.

    Pure function. Does not mutate input candidates; returns a new list of
    shallow-copied dicts annotated with ``hybrid_score`` and component
    scores under ``hybrid_components``.
    """

    def __init__(
        self,
        alpha: float | None = None,
        beta: float | None = None,
        gamma: float | None = None,
    ) -> None:
        a, b, g = _load_weights()
        self.alpha = a if alpha is None else alpha
        self.beta = b if beta is None else beta
        self.gamma = g if gamma is None else gamma

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        *,
        query_time: datetime | None = None,
    ) -> list[dict]:
        if not candidates:
            return []

        texts = [str(c.get("text") or c.get("content") or "") for c in candidates]
        doc_tokens = [_tokenize(t) for t in texts]
        query_tokens = _tokenize(query or "")

        bm25_raw = _bm25_scores(query_tokens, doc_tokens) if query_tokens else [0.0] * len(candidates)
        dense_raw = [float(c.get("score") or 0.0) for c in candidates]

        cue_kind, window = _detect_temporal_window(query or "")
        effective_query_time = query_time or (datetime.now() if cue_kind else None)
        temporal_raw = [
            _temporal_score(
                _coerce_timestamp(c.get("timestamp") or c.get("ts") or c.get("created_at")),
                effective_query_time,
                window,
            )
            for c in candidates
        ]

        bm25_norm = _minmax_normalize(bm25_raw)
        dense_norm = _minmax_normalize(dense_raw)
        # Temporal scores are already in [0, 1].
        temporal_norm = [max(0.0, min(1.0, t)) for t in temporal_raw]

        out: list[dict] = []
        for i, cand in enumerate(candidates):
            final = (
                self.alpha * dense_norm[i]
                + self.beta * bm25_norm[i]
                + self.gamma * temporal_norm[i]
            )
            new_cand = dict(cand)
            new_cand["hybrid_score"] = final
            new_cand["hybrid_components"] = {
                "dense": dense_norm[i],
                "bm25": bm25_norm[i],
                "temporal": temporal_norm[i],
                "weights": {"alpha": self.alpha, "beta": self.beta, "gamma": self.gamma},
            }
            out.append(new_cand)

        out.sort(key=lambda c: c["hybrid_score"], reverse=True)
        return out


__all__ = ["HybridReranker"]
