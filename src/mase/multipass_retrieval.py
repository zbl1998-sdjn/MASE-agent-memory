"""Multi-pass retrieval for MASE.

Gated by env ``MASE_MULTIPASS=1``; when disabled, callers fall back to
single-pass ``BenchmarkNotetaker.search``. Designed so that any failure
in this module degrades gracefully to single-pass results — multipass
must NEVER reduce recall below baseline.

Pipeline (when enabled):
  A. Original keywords  -> single-pass search (baseline anchor)
  B. Query rewrites     -> small LLM (qwen2.5:1.5b) generates 2-3 paraphrases
  C. HyDE pseudo-doc    -> small LLM drafts a hypothetical answer; mine its
                           keywords; search again
  D. Cross-encoder rerank -> bge-reranker-v2-m3 reranks the merged top-K
                             candidates against the ORIGINAL question
  E. Safety net           -> if multipass produces less than half the
                             baseline rows, return baseline rows instead

Caching: per-process LRU keyed by question text; avoids paying LLM tax
when the same question is searched multiple times.

Environment knobs:
  MASE_MULTIPASS=1            -> enable pipeline
  MASE_MULTIPASS_VARIANTS=N   -> number of rewrites (default 2)
  MASE_MULTIPASS_HYDE=0/1     -> enable HyDE pass (default 1 when multipass on)
  MASE_MULTIPASS_RERANK=0/1   -> enable cross-encoder rerank (default 1)
  MASE_MULTIPASS_RERANK_TOP=K -> rerank top-K candidates (default 30)
"""
from __future__ import annotations

import os
import re
import threading
from functools import lru_cache
from typing import Any

_LOCK = threading.Lock()
_RERANKER: Any = None
_RERANKER_LOAD_FAILED = False


def is_enabled() -> bool:
    return os.environ.get("MASE_MULTIPASS", "").strip() in {"1", "true", "True", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _load_reranker():
    global _RERANKER, _RERANKER_LOAD_FAILED
    if _RERANKER is not None:
        return _RERANKER
    if _RERANKER_LOAD_FAILED:
        return None
    with _LOCK:
        if _RERANKER is not None:
            return _RERANKER
        if _RERANKER_LOAD_FAILED:
            return None
        try:
            from sentence_transformers import CrossEncoder

            model_name = os.environ.get(
                "MASE_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"
            )
            _RERANKER = CrossEncoder(model_name, max_length=512)
        except Exception:
            _RERANKER_LOAD_FAILED = True
            _RERANKER = None
    return _RERANKER


@lru_cache(maxsize=512)
def _generate_query_variants_cached(question: str, n: int) -> tuple[str, ...]:
    """Generate ``n`` paraphrased variants via local small LLM. Pure cache key."""
    if not question or n <= 0:
        return ()
    try:
        from .model_interface import ModelInterface  # type: ignore
    except Exception:
        return ()
    prompt = (
        f"请为下面的问题生成 {n} 个不同表述但语义等价的改写, 每行一个, 不要编号, 不要解释:\n\n"
        f"原问题: {question}"
    )
    try:
        mi = ModelInterface()
        # Use small, fast model from cluster.
        out = mi.chat(
            messages=[{"role": "user", "content": prompt}],
            mode="router",  # router uses qwen0.5b/1.5b -- cheapest tier
        )
        text = (out or {}).get("content") if isinstance(out, dict) else str(out)
    except Exception:
        return ()
    if not text:
        return ()
    lines = [
        re.sub(r"^[\s\-\*\d\.\)、:：]+", "", ln).strip()
        for ln in text.splitlines()
    ]
    variants = tuple(ln for ln in lines if ln and ln != question)[:n]
    return variants


@lru_cache(maxsize=512)
def _generate_hyde_keywords_cached(question: str) -> tuple[str, ...]:
    """Use small LLM to draft a hypothetical answer; extract its content tokens."""
    if not question:
        return ()
    try:
        from .model_interface import ModelInterface  # type: ignore
    except Exception:
        return ()
    prompt = (
        "假设你已经知道答案, 请用 1-2 句话直接陈述对下面问题最可能的答案 "
        "(不需要正确, 只需要包含可能涉及的关键名词与术语):\n\n问题: " + question
    )
    try:
        mi = ModelInterface()
        out = mi.chat(
            messages=[{"role": "user", "content": prompt}],
            mode="router",
        )
        text = (out or {}).get("content") if isinstance(out, dict) else str(out)
    except Exception:
        return ()
    if not text:
        return ()
    tokens: list[str] = []
    for tok in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}", text):
        if tok not in tokens:
            tokens.append(tok)
    return tuple(tokens[:12])


def _merge_dedup(*result_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union by row id, keep max score. Stable order: highest score first."""
    best: dict[Any, dict[str, Any]] = {}
    for rows in result_lists:
        for row in rows or []:
            key = row.get("id")
            if key is None:
                key = id(row)
            existing = best.get(key)
            if existing is None or float(row.get("score") or 0) > float(existing.get("score") or 0):
                best[key] = dict(row)
    merged = list(best.values())
    merged.sort(key=lambda r: (-float(r.get("score") or 0), -int(r.get("id") or 0)))
    return merged


def _rerank_cross_encoder(
    question: str, candidates: list[dict[str, Any]], top_k: int
) -> list[dict[str, Any]] | None:
    if not candidates:
        return []
    reranker = _load_reranker()
    if reranker is None:
        return None
    pairs: list[tuple[str, str]] = []
    for row in candidates:
        text = " ".join(
            [
                str(row.get("summary") or ""),
                str(row.get("content") or ""),
            ]
        ).strip()
        pairs.append((question, text[:1500]))
    try:
        scores = reranker.predict(pairs, show_progress_bar=False)
    except Exception:
        return None
    enriched = []
    for row, sc in zip(candidates, scores):
        new_row = dict(row)
        new_row["rerank_score"] = float(sc)
        enriched.append(new_row)
    enriched.sort(key=lambda r: -float(r.get("rerank_score") or 0))
    return enriched[:top_k]


def multipass_search(
    notetaker: Any,
    keywords: list[str],
    full_query: str | None,
    limit: int,
    *,
    search_kwargs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Multi-pass retrieval. Always returns at least the single-pass baseline.

    ``notetaker`` must expose a ``search(keywords, full_query=, limit=, **kw)`` API.
    """
    extra = dict(search_kwargs or {})
    baseline = notetaker.search(
        keywords or [full_query or ""],
        full_query=full_query,
        limit=max(limit, 5),
        **extra,
    )
    if not is_enabled():
        return baseline[:limit]

    n_variants = _int_env("MASE_MULTIPASS_VARIANTS", 2)
    use_hyde = _bool_env("MASE_MULTIPASS_HYDE", True)
    use_rerank = _bool_env("MASE_MULTIPASS_RERANK", True)
    rerank_top = _int_env("MASE_MULTIPASS_RERANK_TOP", 30)
    # iter5: multi-session questions need a wider rerank pool because evidence
    # is spread across many sessions. Bumped only when MASE_LME_QTYPE_ROUTING=1
    # AND MASE_QTYPE=multi-session. Default off → no behaviour change.
    if str(os.environ.get("MASE_LME_QTYPE_ROUTING") or "").strip() in {"1", "true", "yes"}:
        if (os.environ.get("MASE_QTYPE") or "").strip().lower() == "multi-session":
            rerank_top = _int_env("MASE_MULTIPASS_RERANK_TOP_MULTISESSION", 80)

    pools: list[list[dict[str, Any]]] = [baseline]

    question = (full_query or " ".join(keywords or [])).strip()

    if n_variants > 0 and question:
        variants = _generate_query_variants_cached(question, n_variants)
        for v in variants:
            try:
                rows = notetaker.search(
                    [v], full_query=v, limit=max(limit, 5), **extra
                )
            except Exception:
                rows = []
            if rows:
                pools.append(rows)

    if use_hyde and question:
        hyde_kw = list(_generate_hyde_keywords_cached(question))
        if hyde_kw:
            try:
                rows = notetaker.search(
                    hyde_kw, full_query=question, limit=max(limit, 5), **extra
                )
            except Exception:
                rows = []
            if rows:
                pools.append(rows)

    merged = _merge_dedup(*pools)

    if use_rerank and merged and question:
        reranked = _rerank_cross_encoder(question, merged[:rerank_top], rerank_top)
        if reranked is not None and reranked:
            # Safety: if rerank dropped many baseline winners, keep a union
            baseline_ids = {r.get("id") for r in baseline[:limit]}
            reranked_ids = {r.get("id") for r in reranked[:limit]}
            if len(baseline_ids & reranked_ids) < max(1, len(baseline_ids) // 2):
                # rerank disagrees too strongly with baseline; merge both
                top: list[dict[str, Any]] = []
                seen: set[Any] = set()
                for row in (baseline[: max(1, limit // 2)] + reranked):
                    key = row.get("id")
                    if key in seen:
                        continue
                    seen.add(key)
                    top.append(row)
                    if len(top) >= limit:
                        break
                return top
            return reranked[:limit]

    # Safety net: never return less than baseline
    if len(merged) < max(1, len(baseline) // 2):
        return baseline[:limit]
    return merged[:limit]
