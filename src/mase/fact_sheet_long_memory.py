"""长记忆 fact-sheet 构建门面。

本模块负责把完整 chronological memory rows、检索命中的 priority rows 和
evidence scan 合并成 executor 可读的事实表。具体词项扩展、时间推理 ledger、
聚合 ledger 分散在 `fact_sheet_long_memory_*` 子模块中，避免本门面继续膨胀。
"""
from __future__ import annotations

import os
from typing import Any

from .fact_sheet_common import _parse_metadata, strip_memory_prefixes
from .fact_sheet_long_memory_scan import _build_long_memory_evidence_scan
from .topic_threads import detect_text_language


def _local_only_active() -> bool:
    """判断是否处于本地小模型模式，避免直接 import mode_selector 形成循环。

    本地 Ollama 模型（如 qwen2.5:7b）常用 num_ctx≈16384 tokens（约 65K 字符）。
    220K 字符事实表会被静默截断，可能正好丢掉 answer 所在的 evidence_scan
    窗口，因此本地模式必须激进收缩预算。
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
    """构建长记忆完整事实表。

    选择策略：
    1. priority rows 保留检索高分证据；
    2. halo rows 保留同 session 邻近上下文；
    3. non-priority rows 从最近历史倒序补足预算；
    4. 最终按 row id 恢复 chronological 顺序交给 executor。
    """
    if not all_rows:
        return "No prior chat history." if detect_text_language(user_question) == "en" else "无相关历史聊天记录。"
    is_en = detect_text_language(user_question) == "en"
    priority_ids = priority_ids or set()

    local_only = _local_only_active()
    if local_only:
        # 本地预算按 qwen2.5:7b num_ctx=16384 设计：
        # header + evidence_scan + chronological lines + system_prompt + 问题/答案
        # 控制在约 46K 字符，避免 Ollama 截断最关键的 evidence_scan。
        char_budget = min(char_budget, 12_000)
        max_priority = min(max_priority, 16)


    def _render(row: dict[str, Any], idx: int) -> str:
        """把一条 memory row 渲染成带日期/session 标签的证据行。"""
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
    # halo 只沿同一 session 向前/向后扩展，避免把相邻但无关会话混进证据窗口。
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
    # 预算填充顺序体现证据优先级：检索命中 > 同会话上下文 > 最近历史。
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
        # 本地 executor 的 system_prompt 要求遍历 [1]...[K]，因此把 evidence scan
        # 的 [E1]...[EK] 重编号，减少模型格式误读。
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
