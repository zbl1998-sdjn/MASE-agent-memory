from __future__ import annotations

import re
from typing import Any

from .schemas import BenchmarkSample

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _compact_text(text: str) -> str:
    lowered = (text or "").lower()
    lowered = re.sub(r"(?<!\d)\.(?!\d)", " ", lowered)
    lowered = re.sub(r"[^\w\u4e00-\u9fff\.]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _truth_variants(truth: str) -> list[str]:
    raw = (truth or "").strip()
    if not raw:
        return []

    variants: list[str] = [raw]

    without_parens = re.sub(r"\s*\([^)]*\)", "", raw).strip()
    if without_parens and without_parens not in variants:
        variants.append(without_parens)

    for inner in re.findall(r"\(([^)]*)\)", raw):
        candidate = inner.strip()
        if candidate.lower().startswith("or "):
            candidate = candidate[3:].strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    leading_quantity = re.match(r"^([-+]?\d+(?:\.\d+)?(?:\s+[A-Za-z]+){0,1})\b", raw)
    if leading_quantity:
        candidate = leading_quantity.group(1).strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    return variants


def _normalize_number_words(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    return re.sub(
        rf"\b({'|'.join(sorted(_NUMBER_WORDS, key=len, reverse=True))})\b",
        lambda match: _NUMBER_WORDS[match.group(1)],
        normalized,
    )


def _strip_leading_article(text: str) -> str:
    return re.sub(r"^(?:a|an|the)\s+", "", _normalize_text(text))


def _text_variants(text: str) -> list[str]:
    base = _normalize_text(text)
    number_normalized = _normalize_number_words(text)
    stripped = _strip_leading_article(text)
    stripped_number_normalized = _strip_leading_article(number_normalized)
    variants = [
        base,
        _compact_text(base),
        number_normalized,
        _compact_text(number_normalized),
        stripped,
        _compact_text(stripped),
        stripped_number_normalized,
        _compact_text(stripped_number_normalized),
    ]
    deduped: list[str] = []
    for variant in variants:
        if variant and variant not in deduped:
            deduped.append(variant)
    return deduped


def _contains_phrase(answer: str, phrase: str) -> bool:
    normalized_answer = _normalize_text(answer)
    normalized_phrase = _normalize_text(phrase)
    if normalized_phrase and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized_phrase):
        answer_numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", normalized_answer)
        compact_numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", _compact_text(answer))
        return normalized_phrase in answer_numbers or normalized_phrase in compact_numbers
    answer_variants = _text_variants(answer)
    phrase_variants = _text_variants(phrase)
    return any(
        phrase_variant and phrase_variant in answer_variant
        for answer_variant in answer_variants
        for phrase_variant in phrase_variants
    )


def _extract_choice(answer: str) -> str | None:
    text = (answer or "").strip()
    if not text:
        return None
    upper = text.upper()
    # Priority 1: explicit "FINAL ANSWER: X"
    m = re.search(r"FINAL\s*ANSWER\s*[:\-]\s*\(?([A-D])\)?", upper)
    if m:
        return m.group(1)
    # Priority 2: "ANSWER: X" / "答案[:：]X"
    m = re.search(r"(?:ANSWER|答案)\s*[:：\-]\s*\(?([A-D])\)?", upper)
    if m:
        return m.group(1)
    # Priority 3: last standalone letter on its own short line
    for line in reversed([l.strip() for l in upper.splitlines() if l.strip()]):
        if len(line) <= 6:
            mm = re.search(r"\b([A-D])\b", line)
            if mm:
                return mm.group(1)
    # Fallback: first A-D anywhere
    m = re.search(r"\b([A-D])\b", upper)
    return m.group(1) if m else None


def _extract_last_number(answer: str) -> str | None:
    matches = re.findall(r"[-+]?\d+(?:\.\d+)?", answer or "")
    return matches[-1] if matches else None


def score_sample(sample: BenchmarkSample, answer: str) -> dict[str, Any]:
    normalized_answer = _normalize_text(answer)
    truth_variants = _truth_variants(sample.ground_truth)

    if sample.task_type == "multiple_choice":
        extracted = _extract_choice(answer)
        exact = extracted == sample.ground_truth.upper()
        option_text = _normalize_text(str(sample.metadata.get("correct_option_text", "")))
        return {
            "score": 1.0 if exact or (option_text and option_text in normalized_answer) else 0.0,
            "all_matched": bool(exact or (option_text and option_text in normalized_answer)),
            "details": {
                "expected": sample.ground_truth,
                "extracted": extracted,
            },
        }

    if sample.task_type == "math":
        extracted = _extract_last_number(answer)
        exact = extracted == sample.ground_truth
        return {
            "score": 1.0 if exact else 0.0,
            "all_matched": exact,
            "details": {
                "expected": sample.ground_truth,
                "extracted": extracted,
            },
        }

    if sample.task_type == "code_generation":
        keyword_checks = {keyword: keyword.lower() in normalized_answer for keyword in sample.answer_keywords}
        if sample.entry_point:
            keyword_checks[f"def {sample.entry_point}"] = f"def {sample.entry_point}".lower() in normalized_answer
        all_matched = all(keyword_checks.values()) if keyword_checks else bool(answer.strip())
        return {
            "score": 1.0 if all_matched else 0.0,
            "all_matched": all_matched,
            "details": keyword_checks,
        }

    if sample.task_type == "long_context_qa":
        meta = sample.metadata or {}
        mc_letter = str(meta.get("mc_letter", "")).strip().upper() if isinstance(meta, dict) else ""
        if mc_letter in {"A", "B", "C", "D"}:
            extracted = _extract_choice(answer)
            option_text = _normalize_text(str(meta.get("correct_option_text", "")))
            exact = extracted == mc_letter
            text_match = bool(option_text) and option_text in normalized_answer
            return {
                "score": 1.0 if exact or text_match else 0.0,
                "all_matched": bool(exact or text_match),
                "details": {
                    "expected": mc_letter,
                    "extracted": extracted,
                    "text_match": text_match,
                },
            }
        blacklist = {word.lower() for word in sample.word_blacklist}
        keywords = [keyword for keyword in sample.answer_keywords if keyword.lower() not in blacklist]
        if not keywords and sample.ground_truth:
            keywords = truth_variants or [sample.ground_truth]
        keyword_checks = {keyword: _contains_phrase(answer, keyword) for keyword in keywords}
        matched_count = sum(1 for matched in keyword_checks.values() if matched)
        total = max(1, len(keyword_checks))
        return {
            "score": matched_count / total,
            "all_matched": matched_count == total,
            "details": keyword_checks,
        }

    keywords = sample.answer_keywords or (truth_variants if sample.ground_truth else [])
    keyword_checks = {keyword: _contains_phrase(answer, keyword) for keyword in keywords}
    exact = any(_contains_phrase(answer, variant) for variant in truth_variants)
    all_matched = exact or (all(keyword_checks.values()) if keyword_checks else bool(answer.strip()))
    return {
        "score": 1.0 if all_matched else 0.0,
        "all_matched": all_matched,
        "details": {
            "exact_substring": exact,
            "keyword_checks": keyword_checks,
        },
    }
