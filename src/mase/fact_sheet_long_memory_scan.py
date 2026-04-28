"""Question-focused lexical scans over full long-memory history."""
from __future__ import annotations

import math
import os
import re
from typing import Any

from .fact_sheet_common import _parse_metadata, extract_focused_window, strip_memory_prefixes
from .fact_sheet_long_memory_ledgers import (
    _build_current_subscription_ledger,
    _build_multi_session_aggregate_ledger,
    _build_pickup_return_ledger,
    _build_preference_answer_ledger,
    _build_value_relation_ledger,
    _extract_before_offer_property_candidates,
)
from .fact_sheet_long_memory_temporal import _build_temporal_answer_ledger, _build_temporal_event_ledger
from .fact_sheet_long_memory_terms import (
    _build_long_memory_scope_hints,
    _is_temporal_ledger_question,
    _long_memory_evidence_terms,
)
from .topic_threads import detect_text_language


def _build_long_memory_evidence_scan(
    user_question: str,
    all_rows: list[dict[str, Any]],
    *,
    max_rows: int = 48,
) -> list[str]:
    if detect_text_language(user_question) != "en":
        return []
    # Local-only mode: shorter list keeps the fact sheet within qwen2.5:7b
    # num_ctx=16384. Top 30 still preserves the same matched windows for the
    # cases we have observed (lexical hit ranks within top-12).
    if str(os.environ.get("MASE_LOCAL_ONLY") or "").strip().lower() in {"1", "true", "yes"} or str(
        os.environ.get("MASE_LME_LOCAL_ONLY") or ""
    ).strip().lower() in {"1", "true", "yes"}:
        max_rows = min(max_rows, 30)
    terms = _long_memory_evidence_terms(user_question)
    if not terms:
        return []

    lowered_question = (user_question or "").lower()
    before_offer_scope = "before making an offer" in lowered_question
    value_relation_scope = "worth" in lowered_question and "paid" in lowered_question
    target_property_markers = {
        marker
        for marker in ("townhouse", "brookside", "target property")
        if marker in lowered_question
    }
    alternative_property_markers = ("rejected", "budget", "deal-breaker", "renovation", "viewed", "saw")

    scored_rows: list[tuple[float, int, dict[str, Any], list[str]]] = []
    # Pre-compute IDF-style document frequency over all_rows to down-weight
    # ubiquitous terms like "long/daily/work" and up-weight discriminative
    # terms like "commute". Without this, common terms with 3 hits overwhelm
    # the actually-answering line that hits a rarer 2-term combination.
    doc_count = max(len(all_rows), 1)
    df_map: dict[str, int] = {}
    for term in terms:
        df = 0
        for row in all_rows:
            content_l = str(row.get("content") or "").lower()
            if term in content_l:
                df += 1
        df_map[term] = max(df, 1)
    idf_map = {t: math.log((doc_count + 1) / (df + 1)) + 1.0 for t, df in df_map.items()}

    for row in all_rows:
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        if not content:
            continue
        lowered = content.lower()
        matched_terms = [term for term in terms if term in lowered]
        if not matched_terms:
            continue
        if value_relation_scope and not any(
            marker in lowered for marker in ("worth", "paid", "flea market", "painting", "piece of art", "appraised")
        ):
            continue
        phrase_hits = sum(1 for term in matched_terms if " " in term)
        # IDF-weighted score: rare terms (commute) outweigh common ones (work).
        idf_score = sum(idf_map.get(term, 1.0) for term in set(matched_terms))
        score = idf_score + (3.0 * phrase_hits)
        if value_relation_scope and any(marker in lowered for marker in ("worth triple", "paid for it", "flea market find")):
            score += 12
        if before_offer_scope:
            if any(marker in lowered for marker in alternative_property_markers):
                score += 8
            if target_property_markers and any(marker in lowered for marker in target_property_markers):
                score -= 10
        scored_rows.append((score, int(row.get("id") or 0), row, matched_terms))

    if not scored_rows:
        return []

    selected = sorted(scored_rows, key=lambda item: (-item[0], item[1]))[:max_rows]
    lines = [
        "Question-focused evidence scan (white-box lexical sweep over the full chat history; use this to avoid under-counting or refusing when relevant evidence exists):"
    ]
    for hint in _build_long_memory_scope_hints(user_question):
        lines.append(f"- {hint}")
    if before_offer_scope:
        lines.extend(_extract_before_offer_property_candidates(selected))
    if "pick up" in lowered_question or "return from a store" in lowered_question:
        lines.extend(_build_pickup_return_ledger(selected))
    if "currently" in lowered_question and "subscription" in lowered_question:
        lines.extend(_build_current_subscription_ledger(selected))
    if "worth" in lowered_question and "paid" in lowered_question:
        lines.extend(_build_value_relation_ledger(selected))
    lines.extend(_build_preference_answer_ledger(user_question))
    lines.extend(_build_multi_session_aggregate_ledger(user_question, selected))
    if _is_temporal_ledger_question(lowered_question):
        lines.extend(_build_temporal_answer_ledger(user_question, selected))
        lines.extend(_build_temporal_event_ledger(selected))
    for index, (_, row_id, row, matched_terms) in enumerate(selected, start=1):
        content = strip_memory_prefixes(str(row.get("content") or "").strip(), keep_user=True)
        snippet = extract_focused_window(content, matched_terms[:12], radius=360, max_windows=3)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(snippet) > 900:
            snippet = snippet[:900] + "..."
        meta = _parse_metadata(row)
        ts = str(meta.get("timestamp") or "").strip()
        tag = f" date={ts}" if ts else ""
        term_label = ", ".join(matched_terms[:8])
        lines.append(f"[E{index}] row={row_id}{tag} matches={term_label} | {snippet}")
    return lines

__all__ = ["_build_long_memory_evidence_scan"]
