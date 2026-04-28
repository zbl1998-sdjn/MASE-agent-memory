"""Shared text and metadata helpers for fact-sheet builders."""
from __future__ import annotations

import json
from typing import Any


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
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}

__all__ = ["strip_memory_prefixes", "extract_focused_window", "_parse_metadata"]
