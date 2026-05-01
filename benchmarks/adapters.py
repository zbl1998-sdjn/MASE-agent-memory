from __future__ import annotations

import ast
import json
import re
from typing import Any

from .schemas import BenchmarkSample, BenchmarkTurn


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse_history_text(text: str) -> list[BenchmarkTurn]:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []

    session_heading_pattern = re.compile(r"(?:History Chats:)?Session\s+(?P<session>[^\n]+):")
    session_payload_pattern = re.compile(r"(\[.*?\]|\{.*?\})", re.DOTALL)
    session_turns: list[BenchmarkTurn] = []
    session_matches = list(session_heading_pattern.finditer(cleaned))
    for index, match in enumerate(session_matches):
        chunk_start = match.end()
        chunk_end = session_matches[index + 1].start() if index + 1 < len(session_matches) else len(cleaned)
        chunk = cleaned[chunk_start:chunk_end]
        payload_match = session_payload_pattern.search(chunk)
        if not payload_match:
            continue
        entry_text = payload_match.group(1).strip()
        try:
            payload = ast.literal_eval(entry_text)
        except (ValueError, SyntaxError):
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            role = _stringify(entry.get("role")).strip().lower()
            content = _stringify(entry.get("content")).strip()
            if role in {"user", "assistant"} and content:
                session_turns.append(
                    BenchmarkTurn(
                        role="user" if role == "user" else "assistant",
                        content=content,
                        session_id=match.group("session").strip(),
                    )
                )
    if session_turns:
        return session_turns

    pattern = re.compile(
        r"(?P<role>User|Assistant|用户|助手)\s*[:：]\s*(?P<content>.*?)(?=(?:\n(?:User|Assistant|用户|助手)\s*[:：])|\Z)",
        re.DOTALL,
    )
    turns: list[BenchmarkTurn] = []
    for match in pattern.finditer(cleaned):
        role = match.group("role")
        content = match.group("content").strip()
        turns.append(
            BenchmarkTurn(
                role="user" if role in {"User", "用户"} else "assistant",
                content=content,
            )
        )

    if turns:
        return turns

    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
    naive_turns: list[BenchmarkTurn] = []
    role = "user"
    for line in lines:
        naive_turns.append(BenchmarkTurn(role=role, content=line))
        role = "assistant" if role == "user" else "user"
    return naive_turns


def _parse_longmemeval_haystack_sessions(record: dict[str, Any]) -> list[BenchmarkTurn]:
    sessions = record.get("haystack_sessions")
    if not isinstance(sessions, list):
        return []

    session_ids = record.get("haystack_session_ids") if isinstance(record.get("haystack_session_ids"), list) else []
    session_dates = record.get("haystack_dates") if isinstance(record.get("haystack_dates"), list) else []
    turns: list[BenchmarkTurn] = []
    for session_index, session in enumerate(sessions):
        if not isinstance(session, list):
            continue
        session_id = _stringify(session_ids[session_index]) if session_index < len(session_ids) else ""
        session_date = _stringify(session_dates[session_index]) if session_index < len(session_dates) else ""
        for entry in session:
            if not isinstance(entry, dict):
                continue
            role = _stringify(entry.get("role")).strip().lower()
            content = _stringify(entry.get("content")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            turns.append(
                BenchmarkTurn(
                    role="user" if role == "user" else "assistant",
                    content=content,
                    timestamp=session_date or None,
                    session_id=session_id or None,
                )
            )
    return turns


def _detect_longmemeval_history_shape(record: dict[str, Any]) -> str:
    if record.get("focused_input"):
        return "focused_input"
    if record.get("full_input") or record.get("history"):
        return "full_input"
    if record.get("haystack_sessions"):
        return "haystack_sessions"
    return "empty"

def adapt_longmemeval_record(record: dict[str, Any], benchmark_name: str) -> BenchmarkSample:
    sample_id = _stringify(record.get("custom_id") or record.get("id") or record.get("question_id") or "unknown")
    question = _stringify(record.get("question"))
    ground_truth = _stringify(record.get("answer") or record.get("ground_truth"))
    history_shape = _detect_longmemeval_history_shape(record)
    history_text = _stringify(record.get("focused_input") or record.get("full_input") or record.get("history"))
    history = _parse_history_text(history_text)
    if not history:
        history = _parse_longmemeval_haystack_sessions(record)
    return BenchmarkSample(
        id=sample_id,
        benchmark=benchmark_name,
        task_type="long_memory",
        question=question,
        ground_truth=ground_truth,
        history=history,
        answer_keywords=[ground_truth] if ground_truth else [],
        metadata={
            "full_input_tokens": record.get("full_input_tokens"),
            "focused_input_tokens": record.get("focused_input_tokens"),
            "question_type": record.get("question_type"),
            "question_date": record.get("question_date"),
            "history_shape": history_shape,
            "history_turn_count": len(history),
            "haystack_session_count": len(record.get("haystack_sessions") or []) if isinstance(record.get("haystack_sessions"), list) else 0,
        },
    )


def adapt_lveval_record(record: dict[str, Any], benchmark_name: str) -> BenchmarkSample:
    sample_id = _stringify(
        record.get("id")
        or record.get("sample_id")
        or record.get("custom_id")
        or f"{record.get('dataset', 'lveval')}-{record.get('length', 'unknown')}"
    )
    question = _stringify(record.get("question") or record.get("input"))
    raw_answers = record.get("answers")
    if isinstance(raw_answers, list):
        answer = _stringify(raw_answers[0] if raw_answers else "")
    else:
        answer = _stringify(record.get("answer") or record.get("ground_truth"))
    context = _stringify(record.get("context"))
    answer_keywords = record.get("answer_keywords") or []
    word_blacklist = record.get("word_blacklist") or []
    if isinstance(answer_keywords, str):
        answer_keywords = [item.strip() for item in re.split(r"[;,，、]", answer_keywords) if item.strip()]
    if isinstance(word_blacklist, str):
        word_blacklist = [item.strip() for item in re.split(r"[;,，、]", word_blacklist) if item.strip()]
    return BenchmarkSample(
        id=sample_id,
        benchmark=benchmark_name,
        task_type="long_context_qa",
        question=question,
        ground_truth=answer,
        context=context,
        answer_keywords=[_stringify(item) for item in answer_keywords],
        word_blacklist=[_stringify(item) for item in word_blacklist],
        metadata={
            "dataset": record.get("dataset"),
            "length": record.get("length"),
            "language": record.get("language"),
            "confusing_facts": record.get("confusing_facts") or record.get("distractor"),
        },
    )


def adapt_longbench_v2_record(record: dict[str, Any], benchmark_name: str) -> BenchmarkSample:
    sample_id = _stringify(record.get("_id") or record.get("id"))
    base_question = _stringify(record.get("question"))
    choices = {
        "A": _stringify(record.get("choice_A")),
        "B": _stringify(record.get("choice_B")),
        "C": _stringify(record.get("choice_C")),
        "D": _stringify(record.get("choice_D")),
    }
    answer_letter = _stringify(record.get("answer")).strip().upper()
    if answer_letter not in choices:
        answer_letter = "A"
    correct_text = choices.get(answer_letter, "")
    formatted_choices = "\n".join(f"{letter}. {text}" for letter, text in choices.items())
    instruction = (
        "Choose the single best answer. Reply with ONLY the letter A, B, C or D."
    )
    question = f"{base_question}\n\n{formatted_choices}\n\n{instruction}"
    context = _stringify(record.get("context"))
    return BenchmarkSample(
        id=sample_id,
        benchmark=benchmark_name,
        task_type="long_context_qa",
        question=question,
        ground_truth=answer_letter,
        context=context,
        answer_keywords=[answer_letter, correct_text] if correct_text else [answer_letter],
        metadata={
            "domain": record.get("domain"),
            "sub_domain": record.get("sub_domain"),
            "difficulty": record.get("difficulty"),
            "length": record.get("length"),
            "mc_letter": answer_letter,
            "mc_choices": choices,
            "correct_option_text": correct_text,
        },
    )


def adapt_mmlu_record(record: dict[str, Any], benchmark_name: str) -> BenchmarkSample:
    question = _stringify(record.get("input") or record.get("question"))
    sample_id = _stringify(record.get("id") or question[:24])
    options = record.get("choices") or []
    if not options:
        options = [record.get(key) for key in ("A", "B", "C", "D") if record.get(key) is not None]
    normalized_options = []
    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for index, option in enumerate(options):
        normalized_options.append(f"{labels[index]}. {_stringify(option)}")
    answer = _stringify(record.get("target") or record.get("answer") or record.get("label"))
    metadata = {}
    if answer and len(answer) == 1 and answer.upper() in labels[: len(normalized_options)]:
        metadata["correct_option_text"] = normalized_options[labels.index(answer.upper())]
    return BenchmarkSample(
        id=sample_id,
        benchmark=benchmark_name,
        task_type="multiple_choice",
        question=question if not normalized_options else f"{question}\n" + "\n".join(normalized_options),
        ground_truth=answer,
        options=normalized_options,
        metadata=metadata,
    )


def adapt_gpqa_record(record: dict[str, Any], benchmark_name: str) -> BenchmarkSample:
    question = _stringify(record.get("Question") or record.get("question"))
    sample_id = _stringify(record.get("Record ID") or record.get("id") or question[:24])
    options = []
    for key in ("Correct Answer", "Incorrect Answer 1", "Incorrect Answer 2", "Incorrect Answer 3"):
        if record.get(key) is not None:
            options.append(_stringify(record[key]))
    normalized_options = []
    labels = "ABCD"
    for index, option in enumerate(options):
        normalized_options.append(f"{labels[index]}. {option}")
    return BenchmarkSample(
        id=sample_id,
        benchmark=benchmark_name,
        task_type="multiple_choice",
        question=question if not normalized_options else f"{question}\n" + "\n".join(normalized_options),
        ground_truth="A" if normalized_options else _stringify(record.get("Correct Answer")),
        options=normalized_options,
        metadata={"correct_option_text": normalized_options[0] if normalized_options else record.get("Correct Answer")},
    )


def adapt_gsm8k_record(record: dict[str, Any], benchmark_name: str) -> BenchmarkSample:
    question = _stringify(record.get("question"))
    answer = _stringify(record.get("answer"))
    numeric_matches = re.findall(r"####\s*([-+]?\d+(?:\.\d+)?)", answer)
    ground_truth = numeric_matches[-1] if numeric_matches else answer
    return BenchmarkSample(
        id=_stringify(record.get("id") or question[:24]),
        benchmark=benchmark_name,
        task_type="math",
        question=question,
        ground_truth=ground_truth,
        answer_keywords=[ground_truth],
    )


def adapt_humaneval_record(record: dict[str, Any], benchmark_name: str) -> BenchmarkSample:
    prompt = _stringify(record.get("prompt"))
    canonical = _stringify(record.get("canonical_solution"))
    entry_point = _stringify(record.get("entry_point") or "")
    return BenchmarkSample(
        id=_stringify(record.get("task_id") or record.get("id") or entry_point),
        benchmark=benchmark_name,
        task_type="code_generation",
        question=prompt,
        ground_truth=canonical,
        answer_keywords=[f"def {entry_point}"] if entry_point else ["def "],
        entry_point=entry_point or None,
    )
