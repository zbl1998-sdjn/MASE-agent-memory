"""Mode-selection helpers driven by environment + question content.

Centralises the routing-style decisions: what kind of long-context task is
this?  Which executor mode answers it best?  Which notetaker compression
profile to use?  Adding a new task family means editing one tiny module
instead of grepping a 1000-line god class.
"""
from __future__ import annotations

import os

from .markers import (
    EN_DISAMBIGUATION_MARKERS,
    EN_HOT_MEMORY_MARKERS,
    EN_REASONING_MARKERS,
    ZH_DISAMBIGUATION_MARKERS,
    ZH_HOT_MEMORY_MARKERS,
    ZH_REASONING_MARKERS,
    contains_any,
)
from .topic_threads import ENGLISH_RECALL_MARKERS, RECALL_MARKERS, detect_text_language


# ---- Task-context probes (env-driven) ----
def current_task_type() -> str:
    return str(os.environ.get("MASE_TASK_TYPE") or "").strip().lower()


def is_long_context_qa() -> bool:
    return current_task_type() == "long_context_qa"


def is_long_memory() -> bool:
    return current_task_type() == "long_memory"


def use_deterministic_fact_sheet() -> bool:
    return is_long_context_qa() or is_long_memory()


def lveval_dataset() -> str:
    return str(os.environ.get("MASE_LVEVAL_DATASET") or "").strip().lower()


def long_context_length_bucket() -> str:
    """Return the length suffix of the active LV-Eval dataset, e.g. ``256k``.

    Falls back to ``""`` when there is no dataset env or the suffix cannot
    be parsed.  Used to tune ``search_limit`` and fact-sheet window radius
    so long haystacks (128k+) don't starve retrieval.
    """
    ds = lveval_dataset()
    if not ds:
        return ""
    for bucket in ("256k", "128k", "64k", "32k", "16k"):
        if ds.endswith(bucket) or f"_{bucket}" in ds:
            return bucket
    return ""


def long_context_search_limit(default: int = 10) -> int:
    bucket = long_context_length_bucket()
    return {
        "16k": 12,
        "32k": 15,
        "64k": 20,
        "128k": 25,
        "256k": 30,
    }.get(bucket, default)


def long_context_window_radius(default: int = 220) -> int:
    bucket = long_context_length_bucket()
    return {
        "16k": 240,
        "32k": 280,
        "64k": 320,
        "128k": 380,
        "256k": 420,
    }.get(bucket, default)


def is_factrecall_long_context() -> bool:
    if not is_long_context_qa():
        return False
    ds = lveval_dataset()
    return ds.startswith("factrecall") or ds == ""


def is_multidoc_long_context() -> bool:
    if not is_long_context_qa():
        return False
    ds = lveval_dataset()
    if not ds:
        return False
    return not ds.startswith("factrecall")


# ---- Heat / mode selection ----
def determine_memory_heat(user_question: str) -> str:
    lowered = str(user_question or "").lower()
    if contains_any(lowered, ZH_HOT_MEMORY_MARKERS + EN_HOT_MEMORY_MARKERS):
        return "hot"
    if contains_any(lowered, RECALL_MARKERS + ENGLISH_RECALL_MARKERS):
        return "cold"
    return "cold"


def benchmark_profile() -> str:
    return str(os.environ.get("MASE_BENCHMARK_PROFILE") or "").strip().lower()


def lme_question_type() -> str:
    return str(os.environ.get("MASE_QTYPE") or "").strip().lower()


def lme_qtype_routing_enabled() -> bool:
    return str(os.environ.get("MASE_LME_QTYPE_ROUTING") or "").strip() in {"1", "true", "yes"}


def select_notetaker_mode(user_question: str, memory_heat: str) -> str:
    language = detect_text_language(user_question)
    if language == "en":
        return "english_fact_card_ops"
    return "hot_ops" if memory_heat == "hot" else "cold_ops"


def select_executor_mode(user_question: str, fact_sheet: str) -> str:
    language = detect_text_language(user_question)
    if not fact_sheet.strip() or fact_sheet.strip() == "无相关记忆。":
        return "general_answer_reasoning"
    if benchmark_profile() == "nolima_wrapper":
        return "grounded_answer_english_reasoning" if language == "en" else "grounded_answer"
    if benchmark_profile() == "nolima_wrapper_extract":
        return "grounded_long_context_nolima_english" if language == "en" else "grounded_long_context"
    if is_long_context_qa():
        if str(os.environ.get("MASE_LONG_CONTEXT_VARIANT") or "").strip().lower() == "mc":
            return "grounded_long_context_mc"
        if is_multidoc_long_context():
            return "grounded_long_context_multidoc_english" if language == "en" else "grounded_long_context_multidoc"
        return "grounded_long_context_english" if language == "en" else "grounded_long_context"
    if is_long_memory():
        # iter4-retry: when MASE_LME_RETRY=1, force every question to the
        # second-opinion executor (kimi-k2.5 + non-abstain bias prompt).
        # Used by scripts/run_lme_iter4_retry.py for the 103-fail slice.
        if str(os.environ.get("MASE_LME_RETRY") or "").strip() in {"1", "true", "yes"}:
            return "grounded_long_memory_retry_kimi"
        # iter5: per-type executor routing. When MASE_LME_QTYPE_ROUTING=1,
        # route temporal-reasoning questions to a local deep-reasoning model
        # (deepseek-r1:7b) instead of the cloud GLM-5 chain. User explicitly
        # opted in for this category; the general "deepseek = lowest priority"
        # rule still applies to all other paths.
        if lme_qtype_routing_enabled():
            qtype = lme_question_type()
            if qtype == "temporal-reasoning":
                return "grounded_long_memory_deepreason_english" if language == "en" else "grounded_long_memory_deepreason"
        return "grounded_long_memory_cloud_english" if language == "en" else "grounded_long_memory_cloud"
    if language == "en":
        if contains_any(user_question, EN_REASONING_MARKERS):
            return "grounded_analysis_english_reasoning"
        if contains_any(user_question, EN_DISAMBIGUATION_MARKERS) and "candidate" in fact_sheet.lower():
            return "grounded_disambiguation_english_reasoning"
        return "grounded_answer_english_reasoning"
    if contains_any(user_question, ZH_REASONING_MARKERS):
        return "grounded_analysis_reasoning"
    if contains_any(user_question, ZH_DISAMBIGUATION_MARKERS) and "候选裁决表" in fact_sheet:
        return "grounded_disambiguation_reasoning"
    return "grounded_answer"


def verify_mode_for_question(user_question: str) -> str:
    is_en = detect_text_language(user_question) == "en"
    if is_long_context_qa():
        return "grounded_verify_long_context_english" if is_en else "grounded_verify_long_context"
    # When LME verifier escape hatch is on AND we're in long_memory context,
    # use cloud LME-tuned verifier (kimi-k2.5 + temporal/multi-session checklist).
    if is_long_memory() and str(os.environ.get("MASE_LME_VERIFY") or "").strip() in {"1", "true", "yes"}:
        # iter3: type-aware verifier routing (MASE_LME_ROUTE_BY_QID=1).
        # iter2 post-mortem (61.0% overall): regular 69.6% (verifier hurts -0.8pp),
        # gpt4_gen 47.1% (abstract reasoning weak), abstention 3.3%
        # (21/29 semantically correct but phrasing mismatch, 8 true hallucinate).
        if str(os.environ.get("MASE_LME_ROUTE_BY_QID") or "").strip() in {"1", "true", "yes"}:
            bucket = (os.environ.get("MASE_QID_BUCKET") or "").strip().lower()
            if bucket == "abstention":
                return "grounded_verify_lme_abstention_english" if is_en else "grounded_verify_lme_abstention"
            if bucket == "gpt4_gen":
                return "grounded_verify_lme_cot_english" if is_en else "grounded_verify_lme_cot"
            # bucket == "regular" → fall through to lighter verifier
        return "grounded_verify_lme_english" if is_en else "grounded_verify_lme"
    return "grounded_verify_english_reasoning" if is_en else "grounded_verify_reasoning"


def generalizer_mode_for_question(user_question: str) -> str:
    if is_long_memory() and lme_qtype_routing_enabled():
        qtype = lme_question_type()
        if qtype == "single-session-preference":
            return (
                "grounded_long_memory_preference_generalizer_english"
                if detect_text_language(user_question) == "en"
                else "grounded_answer"
            )
        if qtype == "multi-session":
            return (
                "grounded_long_memory_aggregate_generalizer_english"
                if detect_text_language(user_question) == "en"
                else "grounded_answer"
            )
    return "grounded_answer_english_reasoning" if detect_text_language(user_question) == "en" else "grounded_answer"


__all__ = [
    "current_task_type",
    "is_long_context_qa",
    "is_long_memory",
    "use_deterministic_fact_sheet",
    "lveval_dataset",
    "long_context_length_bucket",
    "long_context_search_limit",
    "long_context_window_radius",
    "is_factrecall_long_context",
    "is_multidoc_long_context",
    "determine_memory_heat",
    "benchmark_profile",
    "lme_question_type",
    "lme_qtype_routing_enabled",
    "select_notetaker_mode",
    "select_executor_mode",
    "verify_mode_for_question",
    "generalizer_mode_for_question",
]
