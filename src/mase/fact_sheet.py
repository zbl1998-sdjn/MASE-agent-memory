"""Fact-sheet construction helpers for long-context QA and long-memory chat.

Pure functions that take search results / chat rows and return a single
formatted string ready to be handed to an executor.  Kept stateless so that
new task profiles (e.g. multimodal table chunks) can be added without
disturbing the orchestration engine.
"""
from __future__ import annotations

import json
from typing import Any

from .mode_selector import long_context_window_radius
from .topic_threads import detect_text_language


def strip_memory_prefixes(content: str, keep_user: bool = False) -> str:
    """Drop the User:/Assistant:/Summary:/Entities: scaffolding."""
    if not content:
        return ""
    text = content
    for marker in ("\nSummary:", "\nEntities:", "\nsummary=", "\nentities="):
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
    if not keep_user and text.startswith("User: "):
        asst_idx = text.find("\nAssistant: ")
        if 0 < asst_idx < 600:
            text = text[asst_idx + len("\nAssistant: "):]
    return text.strip()


def extract_focused_window(
    content: str,
    terms_sorted: list[str],
    radius: int = 220,
    max_windows: int = 4,
) -> str:
    """Return one or more verbatim windows around matched terms."""
    if not content:
        return ""
    lowered_content = content.lower()
    match_positions: list[int] = []
    max_match_collect = max(8, max_windows * 2)
    for term in terms_sorted:
        if not term:
            continue
        term_l = term.lower()
        start = 0
        while True:
            idx = lowered_content.find(term_l, start)
            if idx < 0:
                break
            match_positions.append(idx)
            start = idx + max(1, len(term_l))
            if len(match_positions) >= max_match_collect:
                break
        if len(match_positions) >= max_match_collect:
            break
    if not match_positions:
        return content[: 2 * radius] + ("…" if len(content) > 2 * radius else "")
    match_positions.sort()
    merged: list[tuple[int, int]] = []
    for pos in match_positions:
        lo = max(0, pos - radius)
        hi = min(len(content), pos + radius)
        if merged and lo <= merged[-1][1] + 40:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
        if len(merged) >= max_windows:
            break
    snippets = []
    for lo, hi in merged:
        prefix = "…" if lo > 0 else ""
        suffix = "…" if hi < len(content) else ""
        snippets.append(f"{prefix}{content[lo:hi]}{suffix}")
    return " || ".join(snippets)


def _parse_metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata")
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def build_long_memory_full_fact_sheet(
    user_question: str,
    all_rows: list[dict[str, Any]],
    priority_ids: set[int] | None = None,
    char_budget: int = 220_000,
    max_priority: int = 60,
) -> str:
    """Hand the cloud executor the search-ranked top-K rows in chronological order."""
    if not all_rows:
        return "No prior chat history." if detect_text_language(user_question) == "en" else "无相关历史聊天记录。"
    is_en = detect_text_language(user_question) == "en"
    priority_ids = priority_ids or set()

    def _render(row: dict[str, Any], idx: int) -> str:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        if not content:
            return ""
        if len(content) > 2400:
            content = content[:2400] + "…"
        meta = _parse_metadata(row)
        ts = str(meta.get("timestamp") or "").strip()
        sid = str(meta.get("session_id") or "").strip()
        tag_parts: list[str] = []
        if ts:
            tag_parts.append(f"date={ts}")
        if sid:
            tag_parts.append(f"sid={sid[:18]}")
        tag = (" (" + ", ".join(tag_parts) + ")") if tag_parts else ""
        return f"[{idx}]{tag} {content}"

    priority_rows = [r for r in all_rows if int(r.get("id") or 0) in priority_ids][:max_priority]
    non_priority_rows = [r for r in all_rows if int(r.get("id") or 0) not in priority_ids]

    kept_rows: list[dict[str, Any]] = []
    used = 0
    for row in priority_rows:
        line = _render(row, 0)
        if not line:
            continue
        if used + len(line) + 1 > char_budget:
            break
        kept_rows.append(row)
        used += len(line) + 1
    for row in reversed(non_priority_rows):
        line = _render(row, 0)
        if not line:
            continue
        if used + len(line) + 1 > char_budget:
            break
        kept_rows.append(row)
        used += len(line) + 1

    kept_rows.sort(key=lambda r: int(r.get("id") or 0))
    lines = [line for idx, row in enumerate(kept_rows, start=1) if (line := _render(row, idx))]
    header = (
        "Below is the user's chat history (search-ranked relevant entries plus most-recent entries for context, in chronological order, each tagged with date and session id). The answer must be supported by these entries; scan ALL of them and aggregate evidence as needed."
        if is_en
        else "以下是用户聊天历史（检索高分相关条目加上最近若干条上下文，按时间先后排列，每条带日期与会话 id 标签）。答案必须由列出条目支持；请扫描全部条目并按需聚合多条证据。"
    )
    return header + "\n" + "\n".join(lines)


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
