from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
ORACLE_PATH = BASE_DIR / "data" / "longmemeval-official" / "longmemeval_oracle.json"

OFFICIAL_SOURCE_GAPS: dict[str, dict[str, Any]] = {
    "gpt4_2f8be40d": {
        "required_markers": ["Rachel and Mike"],
        "gap_type": "official_source_gap",
        "reason": "The official oracle answer requires Rachel and Mike, but the haystack sessions do not mention Mike.",
    }
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


@lru_cache(maxsize=1)
def _load_oracle_index() -> dict[str, dict[str, Any]]:
    if not ORACLE_PATH.exists():
        return {}
    try:
        raw = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    index: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            question_id = str(item.get("question_id") or "").strip()
            if question_id:
                index[question_id] = item
    return index


def _iter_case_record_paths(case_memory_dir: str | Path) -> list[Path]:
    root = Path(case_memory_dir)
    if not root.exists():
        return []
    paths: list[Path] = []
    for path in root.rglob("*.json"):
        if path.parent.name == "system" or path.name.endswith(".fact_card.json"):
            continue
        paths.append(path)
    return sorted(paths, key=lambda item: item.stat().st_mtime)


def _load_latest_case_record(case_memory_dir: str | Path) -> tuple[dict[str, Any], Path | None]:
    for path in reversed(_iter_case_record_paths(case_memory_dir)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data, path
    return {}, None


def _extract_case_fact_sheet(record: dict[str, Any]) -> str:
    metadata = record.get("metadata")
    chunks: list[str] = []
    if isinstance(metadata, dict):
        for key in ("fact_sheet", "evidence_fact_sheet", "reasoning_workspace", "grounded_analysis"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value.strip())
    assistant_response = record.get("assistant_response")
    if isinstance(assistant_response, str) and assistant_response.strip():
        chunks.append(assistant_response.strip())
    return "\n\n".join(chunks)


def _extract_answer_anchors(answer: str) -> list[str]:
    anchors: list[str] = []
    for match in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", str(answer or "")):
        normalized = str(match).strip()
        if normalized and normalized not in anchors:
            anchors.append(normalized)
    return anchors


def audit_official_source_gap(
    *,
    sample_id: str,
    benchmark: str,
    ground_truth: str,
    case_memory_dir: str | Path,
) -> dict[str, Any] | None:
    if "longmemeval" not in str(benchmark or "").lower():
        return None

    oracle = _load_oracle_index().get(str(sample_id or "").strip())
    if not oracle:
        return None

    configured_gap = OFFICIAL_SOURCE_GAPS.get(str(sample_id or "").strip(), {})
    required_markers = [
        str(marker).strip()
        for marker in configured_gap.get("required_markers", [])
        if str(marker).strip()
    ]
    if not required_markers:
        required_markers = _extract_answer_anchors(ground_truth or str(oracle.get("answer") or ""))

    if not required_markers and not configured_gap:
        return None

    haystack_text = _normalize_text("\n".join(str(item or "") for item in (oracle.get("haystack_sessions") or [])))
    record, record_path = _load_latest_case_record(case_memory_dir)
    case_fact_sheet = _extract_case_fact_sheet(record)
    normalized_case_fact_sheet = _normalize_text(case_fact_sheet)

    missing_from_haystack = [
        marker for marker in required_markers
        if _normalize_text(marker) and _normalize_text(marker) not in haystack_text
    ]
    missing_from_case_fact_sheet = [
        marker for marker in required_markers
        if _normalize_text(marker) and _normalize_text(marker) not in normalized_case_fact_sheet
    ]

    if not missing_from_haystack and not missing_from_case_fact_sheet and not configured_gap:
        return None

    if missing_from_haystack:
        status = "data_gap" if configured_gap else "candidate_data_gap"
        gap_type = str(configured_gap.get("gap_type") or "official_source_gap")
        reason = str(
            configured_gap.get("reason")
            or "Required answer anchors are missing from the official haystack sessions."
        )
    elif missing_from_case_fact_sheet:
        status = "retrieval_gap"
        gap_type = "cross_topic_evidence_gap"
        reason = "Required answer anchors exist in official sources but are still missing from the current case fact sheet."
    else:
        status = "recovered"
        gap_type = str(configured_gap.get("gap_type") or "official_source_gap")
        reason = str(configured_gap.get("reason") or "Previously known official-source gap recovered in the current case.")

    return {
        "status": status,
        "gap_type": gap_type,
        "reason": reason,
        "required_markers": required_markers,
        "missing_from_haystack": missing_from_haystack,
        "missing_from_case_fact_sheet": missing_from_case_fact_sheet,
        "oracle_answer": str(ground_truth or oracle.get("answer") or "").strip(),
        "record_path": str(record_path) if record_path else None,
    }
