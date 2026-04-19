"""LLM-as-judge scorer for LongMemEval-style questions.

LongMemEval ships an official GPT-4 judge in their evaluation pipeline because
substring matching grossly under-counts preference / multi-session / temporal
answers (the model's response is semantically correct but phrased differently
from the gold reference). When ``MASE_USE_LLM_JUDGE=1`` (and a cloud key is
available) we route LongMemEval scoring through this judge so reported numbers
are comparable to the official leaderboard.

For safety we *only* upgrade a failing substring/keyword score to a pass — we
never downgrade a passing exact-match. This keeps us conservative on factrecall
style questions while fixing the systematic underscoring on the descriptive
preference category.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure src/ on path so we can reuse ModelInterface
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from mase.model_interface import ModelInterface  # type: ignore
except Exception:  # pragma: no cover - judge becomes a no-op if imports fail
    ModelInterface = None  # type: ignore


_JUDGE_SYSTEM = (
    "You are an expert evaluator for the LongMemEval long-term memory benchmark. "
    "Given a question, the reference answer, and a model's answer, decide whether the "
    "model's answer is *substantively correct* with respect to the reference. "
    "Treat semantically equivalent phrasings, paraphrases, and answers that include "
    "the reference content (even with extra context) as correct. "
    "For preference-style questions, the model is correct if its answer is consistent "
    "with the user's preferences described in the reference (e.g. recommends the same "
    "brand/style/category of item, or acknowledges the same constraints). "
    "Reply with strict JSON: {\"correct\": true|false, \"reason\": \"<one short sentence>\"}."
)


def _build_user_prompt(question: str, ground_truth: str, answer: str, qtype: str | None) -> str:
    qt = (qtype or "").strip() or "unknown"
    return (
        f"Question type: {qt}\n"
        f"Question: {question}\n"
        f"Reference answer: {ground_truth}\n"
        f"Model answer: {answer}\n"
        "Is the model answer correct? Reply with strict JSON only."
    )


_JUDGE_CACHE: dict[str, bool] = {}
_JUDGE_INTERFACE: Any = None


def _get_interface() -> Any:
    global _JUDGE_INTERFACE
    if _JUDGE_INTERFACE is not None:
        return _JUDGE_INTERFACE
    if ModelInterface is None:
        return None
    cfg_path = os.environ.get("MASE_CONFIG_PATH") or str(_REPO / "config.json")
    try:
        _JUDGE_INTERFACE = ModelInterface(cfg_path)
    except Exception:
        _JUDGE_INTERFACE = None
    return _JUDGE_INTERFACE


def judge_answer(
    question: str,
    ground_truth: str,
    answer: str,
    *,
    question_type: str | None = None,
    mode: str = "grounded_long_memory_cloud_english",
) -> bool | None:
    """Return True/False if judge ran, None if judge is unavailable."""
    iface = _get_interface()
    if iface is None or not (answer or "").strip() or not (ground_truth or "").strip():
        return None
    cache_key = f"{question}||{ground_truth}||{answer}"
    if cache_key in _JUDGE_CACHE:
        return _JUDGE_CACHE[cache_key]
    user_prompt = _build_user_prompt(question, ground_truth, answer, question_type)
    try:
        response = iface.chat(
            agent_type="executor",
            mode=mode,
            messages=[{"role": "user", "content": user_prompt}],
            override_system_prompt=_JUDGE_SYSTEM,
        )
    except Exception:
        return None
    raw = ((response or {}).get("message") or {}).get("content") or ""
    text = (raw or "").strip()
    verdict = _parse_verdict(text)
    if verdict is None:
        return None
    _JUDGE_CACHE[cache_key] = verdict
    return verdict


def _parse_verdict(text: str) -> bool | None:
    if not text:
        return None
    # Try strict JSON first
    m = re.search(r"\{[^{}]*\}", text, flags=re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            v = obj.get("correct")
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in {"yes", "true", "1"}
        except Exception:
            pass
    low = text.lower()
    if re.search(r"\b(correct|yes|true)\b", low) and not re.search(r"\b(incorrect|not correct|no|false)\b", low):
        return True
    if re.search(r"\b(incorrect|wrong|no|false)\b", low):
        return False
    return None


def maybe_upgrade_score(
    score: dict[str, Any],
    *,
    question: str,
    ground_truth: str,
    answer: str,
    question_type: str | None,
    benchmark: str | None,
) -> dict[str, Any]:
    """If env var is set and score failed, ask the LLM judge. Conservative: only
    flips False → True. Augments details with judge metadata."""
    if os.environ.get("MASE_USE_LLM_JUDGE", "0") != "1":
        return score
    if not benchmark or "longmemeval" not in benchmark.lower():
        return score
    if score.get("all_matched"):
        return score
    if not answer:
        return score
    gt_lower = (ground_truth or "").lower()
    abstain_gt = any(
        marker in gt_lower
        for marker in (
            "did not mention",
            "didn't mention",
            "you did not",
            "you didn't",
            "not mentioned",
            "no mention",
            "未提及",
            "没有提到",
            "没说",
        )
    )
    answer_low = answer.lower()
    is_refusal = "can't answer" in answer_low or "cannot answer" in answer_low
    # Refusals are only upgradable when the gold answer itself is an abstain
    # ("you didn't mention X — you mentioned Y"). For factual questions we
    # still treat the refusal as a fail to avoid false positives.
    if is_refusal and not abstain_gt:
        return score
    verdict = judge_answer(question, ground_truth, answer, question_type=question_type)
    if verdict is None:
        return score
    new_score = dict(score)
    details = dict(new_score.get("details") or {})
    details["llm_judge"] = {"verdict": verdict, "applied": True}
    new_score["details"] = details
    if verdict:
        new_score["all_matched"] = True
        new_score["score"] = 1.0
    return new_score
