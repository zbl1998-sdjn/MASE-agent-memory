"""混合召回重排器（BM25 + dense + 时间感知）。

这是可插拔的纯函数模块，仅在调用方设置 ``MASE_HYBRID_RECALL=1`` 时启用。
模块本身不做 I/O，也不发起模型调用，因此可以安全地被无条件导入。

每个候选的最终分数：
    score = α * dense + β * bm25 + γ * temporal

默认权重：α=0.5, β=0.3, γ=0.2。可通过环境变量覆盖：
``MASE_HYBRID_RECALL_WEIGHTS="0.5,0.3,0.2"``.
"""
from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

try:  # 可选依赖；缺失时回退到内置 BM25。
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
    """统一英文 token 与 CJK 单字 token，供 BM25 使用。"""
    if not text:
        return []
    text = text.lower()
    tokens = _TOKEN_RE.findall(text)
    # 为无空格语言补充 CJK 单字 unigram，提升中文召回重排稳定性。
    cjk = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    return tokens + cjk


def _detect_temporal_window(query: str) -> tuple[str | None, timedelta | None]:
    """返回时间线索类型与目标窗口；无时间线索时 cue_kind 为 None。"""
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
    """把候选中的多种时间戳格式宽松转换为 datetime。"""
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
        # 先尝试 ISO8601，再兼容常见日志/日期格式。
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
    """把一组分数压到 0..1；常数序列返回全 0。"""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-12:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


# ---------------------------------------------------------------------------
# 内置 BM25 回退实现：仅在 rank_bm25 未安装时使用。
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
    """优先使用 rank_bm25，失败时回退到内置实现。"""
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
        # 命中问题暗示时间窗的候选给满分，窗外按指数衰减。
        window_s = max(target_window.total_seconds(), 1.0)
        if delta <= window_s:
            return 1.0
        return math.exp(-(delta - window_s) / window_s)
    # 无明确时间线索时，只给温和的新近度偏置（半衰期约 30 天）。
    half_life = 30 * 24 * 3600.0
    return math.exp(-delta / half_life) * 0.5


def _load_weights() -> tuple[float, float, float]:
    """读取重排权重；非法配置回退默认值。"""
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
    """BM25 + dense + 时间感知的重排器。

    该类按纯函数方式工作：不修改输入候选，而是返回浅拷贝后的新列表，并在
    候选上附加 ``hybrid_score`` 与 ``hybrid_components``。
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

        # dense_raw 复用上游召回分数；BM25 和 temporal 在本模块内重算。
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
        # temporal 原始分已经约束在 [0, 1]。
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

        # 调用方通常直接截断 top-K，因此这里返回时已经按最终分降序排序。
        out.sort(key=lambda c: c["hybrid_score"], reverse=True)
        return out


__all__ = ["HybridReranker"]
