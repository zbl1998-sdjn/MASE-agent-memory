"""Long-memory fact-sheet builder facade."""
from __future__ import annotations

import os
from typing import Any

from .fact_sheet_common import _parse_metadata, strip_memory_prefixes
from .fact_sheet_long_memory_scan import _build_long_memory_evidence_scan
from .topic_threads import detect_text_language


def _local_only_active() -> bool:
    """Mirrors mode_selector.local_only_models_enabled() without the import cycle.

    Local Ollama models (qwen2.5:7b) run with num_ctx≈16384 tokens (~65K chars).
    A 220K-char fact sheet gets silently head-truncated by Ollama, dropping the
    very evidence_scan windows that contain the answer. Cap aggressively in
    local-only mode so all evidence stays visible.
    """
    return (
        str(os.environ.get("MASE_LOCAL_ONLY") or "").strip().lower() in {"1", "true", "yes"}
        or str(os.environ.get("MASE_LME_LOCAL_ONLY") or "").strip().lower() in {"1", "true", "yes"}
    )


def build_long_memory_full_fact_sheet(
    user_question: str,
    all_rows: list[dict[str, Any]],
    priority_ids: set[int] | None = None,
    char_budget: int = 220_000,
    max_priority: int = 60,
    max_session_halo_per_session: int = 6,
) -> str:
    """Hand the cloud executor the search-ranked top-K rows in chronological order."""
    if not all_rows:
        return "No prior chat history." if detect_text_language(user_question) == "en" else "无相关历史聊天记录。"
    is_en = detect_text_language(user_question) == "en"
    priority_ids = priority_ids or set()

    local_only = _local_only_active()
    if local_only:
        # Budget envelope (chars) tuned for qwen2.5:7b num_ctx=16384 (~65K chars):
        #   header (~250) + evidence_scan (~27K @ 30 rows × 900 chars) +
        #   chronological lines (cap 12K) + system_prompt (~6K) + question + answer
        #   ≈ 46K chars ≈ 11.5K tokens — safely fits the 16K context.
        char_budget = min(char_budget, 12_000)
        max_priority = min(max_priority, 16)


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
    priority_row_ids = {int(r.get("id") or 0) for r in priority_rows}
    halo_row_ids: set[int] = set()
    halo_counts_by_session: dict[str, int] = {}
    for index, row in enumerate(all_rows):
        row_id = int(row.get("id") or 0)
        if row_id not in priority_row_ids:
            continue
        session_id = str(_parse_metadata(row).get("session_id") or "").strip()
        if not session_id:
            continue
        for neighbor_index in range(index - 1, -1, -1):
            neighbor = all_rows[neighbor_index]
            neighbor_meta = _parse_metadata(neighbor)
            if str(neighbor_meta.get("session_id") or "").strip() != session_id:
                break
            if halo_counts_by_session.get(session_id, 0) >= max_session_halo_per_session:
                break
            neighbor_id = int(neighbor.get("id") or 0)
            if neighbor_id not in priority_row_ids:
                halo_row_ids.add(neighbor_id)
                halo_counts_by_session[session_id] = halo_counts_by_session.get(session_id, 0) + 1
        for neighbor_index in range(index + 1, len(all_rows)):
            neighbor = all_rows[neighbor_index]
            neighbor_meta = _parse_metadata(neighbor)
            if str(neighbor_meta.get("session_id") or "").strip() != session_id:
                break
            if halo_counts_by_session.get(session_id, 0) >= max_session_halo_per_session:
                break
            neighbor_id = int(neighbor.get("id") or 0)
            if neighbor_id not in priority_row_ids:
                halo_row_ids.add(neighbor_id)
                halo_counts_by_session[session_id] = halo_counts_by_session.get(session_id, 0) + 1

    halo_rows = [r for r in all_rows if int(r.get("id") or 0) in halo_row_ids]
    non_priority_rows = [
        r
        for r in all_rows
        if int(r.get("id") or 0) not in priority_row_ids and int(r.get("id") or 0) not in halo_row_ids
    ]

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
    for row in halo_rows:
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
    evidence_scan = _build_long_memory_evidence_scan(user_question, all_rows)
    header = (
        "Below is the user's chat history (search-ranked relevant entries plus most-recent entries for context, in chronological order, each tagged with date and session id). The answer must be supported by these entries; scan ALL of them and aggregate evidence as needed."
        if is_en
        else "以下是用户聊天历史（检索高分相关条目加上最近若干条上下文，按时间先后排列，每条带日期与会话 id 标签）。答案必须由列出条目支持；请扫描全部条目并按需聚合多条证据。"
    )
    sections = [header]
    if local_only and evidence_scan:
        # Renumber [E1]..[EK] → [1]..[K] so it matches the system_prompt's
        # "Walk through ALL windows [1]…[K]" instruction.
        import re as _re
        renumbered: list[str] = []
        counter = 0
        for ln in evidence_scan:
            if _re.match(r"^\[E\d+\]", ln):
                counter += 1
                renumbered.append(_re.sub(r"^\[E\d+\]", f"[{counter}]", ln, count=1))
            else:
                renumbered.append(ln)
        sections.append("\n".join(renumbered))
        priority_context_rows = sorted(
            [r for r in all_rows if int(r.get("id") or 0) in (priority_row_ids | halo_row_ids)],
            key=lambda row: int(row.get("id") or 0),
        )
        if priority_context_rows:
            local_context_budget = 3200
            local_context_used = 0
            local_context_lines: list[str] = []
            for idx, row in enumerate(priority_context_rows, start=1):
                line = _render(row, idx)
                if not line:
                    continue
                if local_context_used + len(line) + 1 > local_context_budget:
                    break
                local_context_lines.append(line)
                local_context_used += len(line) + 1
            if local_context_lines:
                label = (
                    "Priority evidence rows (verbatim chronology for exact wording):"
                    if is_en
                    else "重点证据原文（保留原始时间顺序，便于抽取精确措辞）："
                )
                sections.append(label)
                sections.append("\n".join(local_context_lines))
        return "\n".join(sections)
    if evidence_scan:
        sections.append("\n".join(evidence_scan))
    sections.append("\n".join(lines))
    return "\n".join(sections)

__all__ = ["build_long_memory_full_fact_sheet"]
