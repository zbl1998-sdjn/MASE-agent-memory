"""MASE 多轮检索流水线。

该能力由 ``MASE_MULTIPASS=1`` 门禁控制；关闭时调用方退回单轮
``BenchmarkNotetaker.search``。本模块设计原则是“失败即优雅降级到单轮结果”，
multipass 绝不能让召回低于 baseline。

启用后的流水线：
  A. 原始关键词       -> 单轮检索，作为 baseline 锚点
  B. 查询改写         -> 小模型生成 2-3 个等价改写
  C. HyDE 伪文档      -> 小模型假写答案，从中挖关键词再次检索
  D. Cross-encoder 重排 -> bge-reranker-v2-m3 用原问题重排合并后的 top-K
  E. 安全网           -> multipass 结果少于 baseline 一半时返回 baseline

缓存：按问题文本做进程内 LRU，避免同一问题多次搜索时重复支付 LLM 成本。

环境开关：
  MASE_MULTIPASS=1            -> 启用流水线
  MASE_MULTIPASS_VARIANTS=N   -> 改写数量，默认 2
  MASE_MULTIPASS_HYDE=0/1     -> 启用 HyDE，默认随 multipass 开启
  MASE_MULTIPASS_RERANK=0/1   -> 启用 cross-encoder 重排，默认开启
  MASE_MULTIPASS_RERANK_TOP=K -> 重排 top-K 候选，默认 30
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
    """读取 multipass 总开关。"""
    return os.environ.get("MASE_MULTIPASS", "").strip() in {"1", "true", "True", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    """读取整数环境变量，非法值回退默认。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    """读取布尔环境变量，非法/空值回退默认。"""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _load_reranker():
    """懒加载 cross-encoder，并记住加载失败状态避免反复尝试。"""
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
    """用本地小模型生成 ``n`` 个等价改写，并按问题文本缓存。"""
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
        variants_mode = os.environ.get("MASE_QUERY_VARIANTS_MODE", "router").strip() or "router"
        out = mi.chat(
            messages=[{"role": "user", "content": prompt}],
            mode=variants_mode,
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
    """用小模型生成假设答案，再抽取其中的内容 token。"""
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
    """按行 id 合并去重，并保留最高分；输出按分数稳定降序。"""
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
    """用 cross-encoder 对候选重排；不可用或失败时返回 None。"""
    if not candidates:
        return []
    reranker = _load_reranker()
    if reranker is None:
        return None
    pairs: list[tuple[str, str]] = []
    for row in candidates:
        # 输入长度受模型限制，重排只取摘要+正文的前部证据。
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
    """执行多轮检索，并保证不会低于单轮 baseline。

    ``notetaker`` 必须暴露 ``search(keywords, full_query=, limit=, **kw)`` API。
    """
    extra = dict(search_kwargs or {})
    # baseline 始终先跑，既作为召回锚点，也作为所有失败路径的兜底。
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
    # iter5：multi-session 题证据分布在多会话，需放大重排池。只有同时开启
    # MASE_LME_QTYPE_ROUTING 且 MASE_QTYPE=multi-session 时生效，默认不改变行为。
    if str(os.environ.get("MASE_LME_QTYPE_ROUTING") or "").strip() in {"1", "true", "yes"}:
        if (os.environ.get("MASE_QTYPE") or "").strip().lower() == "multi-session":
            rerank_top = _int_env("MASE_MULTIPASS_RERANK_TOP_MULTISESSION", 80)

    pools: list[list[dict[str, Any]]] = [baseline]

    question = (full_query or " ".join(keywords or [])).strip()

    if n_variants > 0 and question:
        # 改写查询拓展召回面；任一改写失败都只丢弃该支路。
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
        # HyDE 支路用假设答案挖潜在实体/术语，尤其补足原问题缺少关键词的情况。
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
            # 安全网：如果重排丢掉过多 baseline 优胜者，就合并 baseline 与 rerank。
            baseline_ids = {r.get("id") for r in baseline[:limit]}
            reranked_ids = {r.get("id") for r in reranked[:limit]}
            if len(baseline_ids & reranked_ids) < max(1, len(baseline_ids) // 2):
                # 重排与 baseline 分歧过大，按半个 baseline + rerank 的顺序合并。
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

    # 最后一层安全网：绝不返回明显少于 baseline 的结果。
    if len(merged) < max(1, len(baseline) // 2):
        return baseline[:limit]
    return merged[:limit]
