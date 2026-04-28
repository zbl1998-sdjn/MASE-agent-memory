"""Fact-sheet construction facade for long-context QA and long-memory chat.

The implementation is split by responsibility:
- fact_sheet_common: shared text/metadata helpers
- fact_sheet_candidates: long-context candidate disambiguation tables
- fact_sheet_long_memory: LongMemEval/long-memory evidence scans and ledgers
"""
from __future__ import annotations

from typing import Any

from .fact_sheet_candidates import _build_candidate_table, _build_cjk_candidate_table
from .fact_sheet_common import _parse_metadata, extract_focused_window, strip_memory_prefixes
from .fact_sheet_long_memory import build_long_memory_full_fact_sheet
from .mode_selector import long_context_window_radius
from .topic_threads import detect_text_language


def build_long_context_fact_sheet(
    user_question: str,
    search_results: list[dict[str, Any]],
    notetaker,  # BenchmarkNotetaker, used only for _extract_terms
    *,
    multidoc: bool,
    long_memory: bool,
) -> str:
    """Deterministic, evidence-preserving fact sheet for long-context QA."""
    if not search_results:
        return "无相关记忆。" if detect_text_language(user_question) != "en" else "No relevant memory."
    is_en = detect_text_language(user_question) == "en"
    terms = notetaker._extract_terms([], full_query=user_question)
    terms_sorted = sorted({t for t in terms if t}, key=lambda t: (-len(t), t))
    if long_memory:
        window_radius = 420
        max_windows_per_chunk = 4
        header = (
            "Retrieved evidence from the user's past chat history (top-K candidate sessions, ordered by relevance score). Treat each [n] as a verbatim window from a real prior conversation; cite from these only and never invent facts."
            if is_en
            else "以下是检索到的用户历史聊天证据（按相关性分数排序的候选会话原文窗口）。仅依据 [n] 中的原文作答，不要编造记忆里没有的事实。"
        )
    elif multidoc:
        window_radius = max(380, long_context_window_radius(default=380))
        max_windows_per_chunk = 6
        header = (
            "Retrieved evidence from a long, multi-document context. Multiple documents may discuss similar entities and a few inserted sentences may be misleading; cross-check before answering."
            if is_en
            else "以下是从长上下文里检索到的多文档证据。不同文档可能涉及相似实体，部分插入语句可能具有干扰性；请交叉验证后作答。"
        )
    else:
        window_radius = long_context_window_radius(default=220)
        max_windows_per_chunk = 4
        header = (
            "Retrieved evidence (verbatim windows around matched terms, ordered by relevance score):"
            if is_en
            else "检索到的候选证据（按相关性分数从高到低，匹配词周围的原文窗口）："
        )
    lines: list[str] = [header]
    if is_en:
        candidate_table = _build_candidate_table(user_question, search_results, terms_sorted)
        if candidate_table:
            lines.extend(candidate_table)
    else:
        candidate_table = _build_cjk_candidate_table(user_question, search_results, terms_sorted)
        if candidate_table:
            lines.extend(candidate_table)
    for index, item in enumerate(search_results, start=1):
        content = strip_memory_prefixes(str(item.get("content") or "").strip())
        if not content:
            continue
        score = item.get("score")
        score_tag = f" (score={score})" if score is not None else ""
        ts_tag = ""
        if long_memory:
            meta_obj = _parse_metadata(item)
            ts = str(meta_obj.get("timestamp") or "").strip()
            if ts:
                ts_tag = f" (date={ts})"
        window_text = extract_focused_window(
            content,
            terms_sorted,
            radius=window_radius,
            max_windows=max_windows_per_chunk,
        )
        lines.append(f"[{index}]{score_tag}{ts_tag} {window_text}")
    return "\n".join(lines)


__all__ = [
    "strip_memory_prefixes",
    "extract_focused_window",
    "build_long_memory_full_fact_sheet",
    "build_long_context_fact_sheet",
]

__all__ = [
    "strip_memory_prefixes",
    "extract_focused_window",
    "build_long_memory_full_fact_sheet",
    "build_long_context_fact_sheet",
]
