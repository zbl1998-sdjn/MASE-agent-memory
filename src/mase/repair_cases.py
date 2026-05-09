from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mase.audit_log import sanitize_audit_value

ROOT = Path(__file__).resolve().parents[2]
VALID_REPAIR_CASE_STATUSES = (
    "open",
    "diagnosed",
    "pending_approval",
    "approved",
    "executed",
    "failed",
    "validated",
    "closed",
)
ALLOWED_REPAIR_CASE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("diagnosed", "failed", "closed"),
    "diagnosed": ("pending_approval", "failed", "closed"),
    "pending_approval": ("approved", "failed", "closed"),
    "approved": ("executed", "failed", "closed"),
    "executed": ("validated", "failed"),
    "failed": ("open", "closed"),
    "validated": ("closed",),
    "closed": (),
}


def resolve_repair_case_path() -> Path:
    raw_path = str(os.environ.get("MASE_REPAIR_CASE_PATH") or "").strip()
    return Path(raw_path).expanduser().resolve() if raw_path else (ROOT / "memory" / "repair_cases.jsonl").resolve()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized not in VALID_REPAIR_CASE_STATUSES:
        raise ValueError(f"invalid repair case status: {status}")
    return normalized


def _append_case(case: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    case_path = path or resolve_repair_case_path()
    case_path.parent.mkdir(parents=True, exist_ok=True)
    with case_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
    return case


def _read_case_snapshots(*, path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    case_path = path or resolve_repair_case_path()
    metadata: dict[str, Any] = {
        "path": str(case_path),
        "exists": case_path.exists(),
        "skipped_count": 0,
        "skipped_lines": [],
    }
    if not case_path.exists():
        return [], metadata
    snapshots: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(case_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            metadata["skipped_count"] += 1
            metadata["skipped_lines"].append(line_number)
            continue
        if isinstance(payload, dict) and payload.get("case_id"):
            snapshots.append(payload)
    return snapshots, metadata


def create_repair_case(
    *,
    issue_type: str,
    symptom: str,
    evidence: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    actor_id: str = "system",
    path: Path | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    case = {
        "case_id": f"repair_{uuid.uuid4().hex[:16]}",
        "status": "open",
        "issue_type": str(issue_type or "incorrect_memory").strip() or "incorrect_memory",
        "symptom": str(symptom or "").strip(),
        "evidence": sanitize_audit_value(evidence or {}),
        "scope": sanitize_audit_value(scope or {}),
        "created_at": now,
        "updated_at": now,
        "created_by": actor_id,
        "events": [
            {
                "event_id": uuid.uuid4().hex,
                "created_at": now,
                "actor_id": actor_id,
                "action": "create",
                "from_status": None,
                "to_status": "open",
                "note": None,
                "metadata": {},
            }
        ],
    }
    return _append_case(case, path=path)


def _latest_cases(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        case_id = str(snapshot.get("case_id") or "")
        if case_id:
            latest[case_id] = snapshot
    return latest


def get_repair_case(case_id: str, *, path: Path | None = None) -> dict[str, Any] | None:
    snapshots, _ = _read_case_snapshots(path=path)
    return _latest_cases(snapshots).get(case_id)


def list_repair_cases(
    *,
    status: str | None = None,
    issue_type: str | None = None,
    limit: int = 100,
    path: Path | None = None,
) -> dict[str, Any]:
    snapshots, metadata = _read_case_snapshots(path=path)
    cases = list(_latest_cases(snapshots).values())
    if status:
        normalized_status = _validate_status(status)
        cases = [case for case in cases if case.get("status") == normalized_status]
    if issue_type:
        cases = [case for case in cases if case.get("issue_type") == issue_type]
    cases.sort(key=lambda case: str(case.get("updated_at") or ""), reverse=True)
    capped_limit = max(1, min(int(limit), 500))
    summary = {
        "total_count": len(cases),
        "by_status": {item: sum(1 for case in cases if case.get("status") == item) for item in VALID_REPAIR_CASE_STATUSES},
    }
    return {"cases": cases[:capped_limit], "summary": summary, "metadata": metadata}


def transition_repair_case(
    *,
    case_id: str,
    status: str,
    actor_id: str = "system",
    note: str | None = None,
    metadata: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    next_status = _validate_status(status)
    current = get_repair_case(case_id, path=path)
    if not current:
        raise KeyError(case_id)
    current_status = _validate_status(str(current.get("status") or "open"))
    if next_status not in ALLOWED_REPAIR_CASE_TRANSITIONS[current_status]:
        raise ValueError(f"invalid repair case transition: {current_status} -> {next_status}")
    now = _now_iso()
    events = list(current.get("events") or [])
    events.append(
        {
            "event_id": uuid.uuid4().hex,
            "created_at": now,
            "actor_id": actor_id,
            "action": "transition",
            "from_status": current_status,
            "to_status": next_status,
            "note": note,
            "metadata": sanitize_audit_value(metadata or {}),
        }
    )
    updated = {**current, "status": next_status, "updated_at": now, "events": events}
    return _append_case(updated, path=path)


def attach_repair_case_diff(
    *,
    case_id: str,
    diff: dict[str, Any],
    actor_id: str = "system",
    path: Path | None = None,
) -> dict[str, Any]:
    current = get_repair_case(case_id, path=path)
    if not current:
        raise KeyError(case_id)
    current_status = _validate_status(str(current.get("status") or "open"))
    if current_status not in {"open", "diagnosed"}:
        raise ValueError(f"repair diff cannot be proposed from status: {current_status}")
    now = _now_iso()
    events = list(current.get("events") or [])
    events.append(
        {
            "event_id": uuid.uuid4().hex,
            "created_at": now,
            "actor_id": actor_id,
            "action": "diff_proposed",
            "from_status": current_status,
            "to_status": "diagnosed",
            "note": None,
            "metadata": {"proposal_id": diff.get("proposal_id")},
        }
    )
    updated = {
        **current,
        "status": "diagnosed",
        "updated_at": now,
        "diff_proposal": sanitize_audit_value(diff),
        "events": events,
    }
    return _append_case(updated, path=path)


def attach_repair_case_sandbox(
    *,
    case_id: str,
    sandbox_report: dict[str, Any],
    actor_id: str = "system",
    path: Path | None = None,
) -> dict[str, Any]:
    current = get_repair_case(case_id, path=path)
    if not current:
        raise KeyError(case_id)
    current_status = _validate_status(str(current.get("status") or "open"))
    if current_status not in {"diagnosed", "pending_approval"}:
        raise ValueError(f"repair sandbox cannot run from status: {current_status}")
    now = _now_iso()
    events = list(current.get("events") or [])
    events.append(
        {
            "event_id": uuid.uuid4().hex,
            "created_at": now,
            "actor_id": actor_id,
            "action": "sandbox_validated",
            "from_status": current_status,
            "to_status": current_status,
            "note": None,
            "metadata": {
                "proposal_id": sandbox_report.get("proposal_id"),
                "safe_to_execute": sandbox_report.get("safe_to_execute"),
            },
        }
    )
    updated = {
        **current,
        "updated_at": now,
        "sandbox_report": sanitize_audit_value(sandbox_report),
        "events": events,
    }
    return _append_case(updated, path=path)


def attach_repair_case_execution(
    *,
    case_id: str,
    execution_report: dict[str, Any],
    actor_id: str = "system",
    path: Path | None = None,
) -> dict[str, Any]:
    current = get_repair_case(case_id, path=path)
    if not current:
        raise KeyError(case_id)
    current_status = _validate_status(str(current.get("status") or "open"))
    if current_status != "approved":
        raise ValueError(f"repair execution cannot run from status: {current_status}")
    now = _now_iso()
    events = list(current.get("events") or [])
    events.append(
        {
            "event_id": uuid.uuid4().hex,
            "created_at": now,
            "actor_id": actor_id,
            "action": "executed",
            "from_status": current_status,
            "to_status": "executed",
            "note": None,
            "metadata": {
                "execution_id": execution_report.get("execution_id"),
                "mutation_count": execution_report.get("mutation_count"),
            },
        }
    )
    updated = {
        **current,
        "status": "executed",
        "updated_at": now,
        "execution_report": sanitize_audit_value(execution_report),
        "events": events,
    }
    return _append_case(updated, path=path)


__all__ = [
    "ALLOWED_REPAIR_CASE_TRANSITIONS",
    "VALID_REPAIR_CASE_STATUSES",
    "attach_repair_case_diff",
    "attach_repair_case_execution",
    "attach_repair_case_sandbox",
    "create_repair_case",
    "get_repair_case",
    "list_repair_cases",
    "resolve_repair_case_path",
    "transition_repair_case",
]
