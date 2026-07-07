"""语义键归并(投影专用):把同义 key 归并到既有 key,让 supersede 链接上。

自然语言抽取对同一事实常产出不同 key(``running_5k_best_time`` vs
``running_personal_best_time``),治理层 supersede 靠 (subject, predicate) 键匹配,
键不一致就双 active、现行值判定失效(2026-07-08 POC 取证)。本模块用与语义
召回同一套 bge-m3 通道,对新 key 在实体已有 active key 里找语义最近者:
cosine ≥ 阈值即复用既有 key。opt-in(``MASE_KEY_MERGE=1``),默认关。
"""
from __future__ import annotations

import os

from .semantic_discovery import embed_model_name, embed_texts

DEFAULT_KEY_MERGE_THRESHOLD = 0.75


def key_merge_enabled() -> bool:
    """opt-in 开关;默认关,投影键行为不变。"""
    return os.environ.get("MASE_KEY_MERGE", "").strip() == "1"


def _threshold() -> float:
    raw = os.environ.get("MASE_KEY_MERGE_THRESHOLD", "").strip()
    if not raw:
        return DEFAULT_KEY_MERGE_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_KEY_MERGE_THRESHOLD


def _cosine(a: list[float], b: list[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm > 1e-12 else 0.0


def canonical_key(
    new_key: str,
    existing_keys: list[str],
    *,
    threshold: float | None = None,
    model: str | None = None,
) -> str:
    """把 new_key 归并到语义最近的 existing_key(cosine ≥ 阈值);否则原样返回。

    完全字面相等直接返回(零 embed 成本);existing 为空也直接返回。
    键短语用下划线转空格后嵌入,让 "running_5k_best_time" 与
    "running personal best time" 落在可比语义空间。
    """
    if not new_key or new_key in existing_keys:
        return new_key
    candidates = [k for k in dict.fromkeys(existing_keys) if k and k != new_key]
    if not candidates:
        return new_key
    limit = threshold if threshold is not None else _threshold()
    texts = [new_key.replace("_", " ")] + [k.replace("_", " ") for k in candidates]
    vectors = embed_texts(texts, model=model or embed_model_name())
    if len(vectors) != len(texts):
        return new_key
    query = vectors[0]
    best_key = new_key
    best_sim = limit
    for key, vector in zip(candidates, vectors[1:], strict=True):
        sim = _cosine(query, vector)
        if sim >= best_sim:
            best_sim = sim
            best_key = key
    return best_key


__all__ = ["DEFAULT_KEY_MERGE_THRESHOLD", "canonical_key", "key_merge_enabled"]
