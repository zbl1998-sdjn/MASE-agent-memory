from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ENGLISH_REASONING_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "did",
    "do",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "the",
    "this",
    "to",
    "what",
    "when",
    "which",
    "who",
    "with",
}


@dataclass(frozen=True)
class ReasoningWorkspace:
    operation: str
    focus_entities: list[str]
    target_unit: str
    sub_tasks: list[str]
    verification_focus: list[str]
    deterministic_answer: str
    evidence_confidence: str
    verifier_action: str
    followup_needed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "focus_entities": list(self.focus_entities),
            "target_unit": self.target_unit,
            "sub_tasks": list(self.sub_tasks),
            "verification_focus": list(self.verification_focus),
            "deterministic_answer": self.deterministic_answer,
            "evidence_confidence": self.evidence_confidence,
            "verifier_action": self.verifier_action,
            "followup_needed": self.followup_needed,
        }

    def to_text(self) -> str:
        lines = ["Reasoning workspace:"]
        lines.append(f"- operation={self.operation}")
        if self.focus_entities:
            lines.append(f"- focus_entities={'; '.join(self.focus_entities)}")
        if self.target_unit:
            lines.append(f"- target_unit={self.target_unit}")
        if self.sub_tasks:
            lines.append(f"- sub_tasks={' | '.join(self.sub_tasks)}")
        if self.verification_focus:
            lines.append(f"- verification_focus={' | '.join(self.verification_focus)}")
        if self.deterministic_answer:
            lines.append(f"- deterministic_answer={self.deterministic_answer}")
        lines.append(f"- evidence_confidence={self.evidence_confidence or 'unknown'}")
        lines.append(f"- verifier_action={self.verifier_action or 'unknown'}")
        lines.append(f"- followup_needed={'yes' if self.followup_needed else 'no'}")
        return "\n".join(lines)


def _dedupe_strings(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(normalized)
    return result


def _is_english_question(question: str) -> bool:
    ascii_letters = len(re.findall(r"[A-Za-z]", question))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", question))
    return ascii_letters > chinese_chars


def _classify_operation(question: str) -> str:
    lowered = str(question or "").lower()
    if any(marker in lowered for marker in ("how much more", "how much less", "difference", "compare")):
        return "difference"
    if any(marker in lowered for marker in ("how long", "how many days", "how many weeks", "how many hours", "duration")):
        return "duration"
    if any(marker in lowered for marker in ("how much", "total cost", "total money", "spent", "paid", "raised", "earned")):
        return "money"
    if any(marker in lowered for marker in ("how many", "count", "number of", "in total", "altogether")):
        return "count"
    if any(marker in lowered for marker in ("most recently", "latest", "earliest", "before", "after")):
        return "chronology"
    if any(marker in lowered for marker in ("who", "which", "what is the name", "what's the name", "name of")):
        return "disambiguation"
    return "lookup"


def _extract_target_unit(question: str) -> str:
    lowered = str(question or "").lower()
    unit_markers = (
        "minutes",
        "minute",
        "hours",
        "hour",
        "days",
        "day",
        "weeks",
        "week",
        "months",
        "month",
        "years",
        "year",
        "times",
        "time",
        "items",
        "item",
        "%",
        "dollars",
        "dollar",
    )
    for marker in unit_markers:
        if marker in lowered:
            return marker
    return "$" if "how much" in lowered or "cost" in lowered or "price" in lowered else ""


def _extract_focus_entities(question: str) -> list[str]:
    source = str(question or "").strip()
    if not source:
        return []
    candidates: list[str] = []
    candidates.extend(match.strip() for match in re.findall(r"\"([^\"]{2,80})\"", source))
    if _is_english_question(source):
        for match in re.findall(r"\b([A-Z][A-Za-z0-9'&\-]+(?:\s+[A-Z][A-Za-z0-9'&\-]+){0,3})\b", source):
            if match not in {"How", "What", "Which", "Who", "When", "Did"}:
                candidates.append(match.strip())
        tokens = [
            token
            for token in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", source.lower())
            if token not in ENGLISH_REASONING_STOPWORDS
        ]
        if tokens:
            candidates.extend(tokens[:8])
    else:
        candidates.extend(re.findall(r"[\u4e00-\u9fff]{2,12}", source))
    return _dedupe_strings(candidates)[:8]


def _extract_fact_sheet_value(fact_sheet: str, key: str) -> str:
    match = re.search(rf"{re.escape(key)}=([^\n]+)", str(fact_sheet or ""))
    return match.group(1).strip() if match else ""


def _extract_deterministic_answer(fact_sheet: str) -> str:
    source = str(fact_sheet or "")
    direct_patterns = [
        r"deterministic_answer=([^\n]+)",
        r"Deterministic chronology answer:\s*([^\n]+)",
        r"Deterministic item count:\s*([^\n]+)",
        r"Deterministic count:\s*([^\n]+)",
        r"Deterministic money delta:\s*([^\n]+)",
        r"Deterministic delta:\s*([^\n]+)",
        r"Deterministic money total:\s*([^\n]+)",
        r"Deterministic money sum:\s*([^\n]+)",
        r"Deterministic sum:\s*([^\n]+)",
        r"Deterministic answer:\s*([^\n]+)",
    ]
    for pattern in direct_patterns:
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            value = re.sub(r"\s*\|.*$", "", value).strip()
            value = re.sub(r"\s*\(.*$", "", value).strip()
            if value:
                return value
    return ""


def _default_sub_tasks(operation: str) -> list[str]:
    if operation in {"count", "money", "difference", "duration"}:
        return ["retrieve evidence", "verify coverage", f"deterministic {operation}", "final answer"]
    if operation == "chronology":
        return ["retrieve evidence", "order by time", "select best candidate", "final answer"]
    if operation == "disambiguation":
        return ["retrieve candidates", "compare supports", "reject distractors", "final answer"]
    return ["retrieve evidence", "verify support", "final answer"]


def _default_verification_focus(operation: str, question: str) -> list[str]:
    lowered = str(question or "").lower()
    focus: list[str] = []
    if operation == "count":
        focus.extend(["duplicate suppression", "entity coverage"])
    elif operation == "money":
        focus.extend(["entity-amount binding", "duplicate suppression"])
    elif operation == "difference":
        focus.extend(["two-side amount binding", "difference correctness"])
    elif operation == "duration":
        focus.extend(["unit normalization", "event deduplication"])
    elif operation == "chronology":
        focus.extend(["time ordering", "latest/earliest selection"])
    elif operation == "disambiguation":
        focus.extend(["candidate separation", "direct evidence"])
    if "name" in lowered or "who" in lowered:
        focus.append("name completeness")
    if "total" in lowered or "in total" in lowered:
        focus.append("aggregation completeness")
    return _dedupe_strings(focus)


def build_reasoning_workspace(
    question: str,
    fact_sheet: str,
    planner_sub_tasks: list[str] | None = None,
    planner_verification_focus: list[str] | None = None,
) -> ReasoningWorkspace:
    operation = _classify_operation(question)
    evidence_confidence = _extract_fact_sheet_value(fact_sheet, "evidence_confidence") or "unknown"
    verifier_action = _extract_fact_sheet_value(fact_sheet, "verifier_action") or "unknown"
    deterministic_answer = _extract_deterministic_answer(fact_sheet)
    sub_tasks = _dedupe_strings(planner_sub_tasks or _default_sub_tasks(operation))
    verification_focus = _dedupe_strings(
        list(planner_verification_focus or []) + _default_verification_focus(operation, question)
    )
    followup_needed = verifier_action in {"verify", "refuse"} and not deterministic_answer
    return ReasoningWorkspace(
        operation=operation,
        focus_entities=_extract_focus_entities(question),
        target_unit=_extract_target_unit(question),
        sub_tasks=sub_tasks,
        verification_focus=verification_focus,
        deterministic_answer=deterministic_answer,
        evidence_confidence=evidence_confidence,
        verifier_action=verifier_action,
        followup_needed=followup_needed,
    )
