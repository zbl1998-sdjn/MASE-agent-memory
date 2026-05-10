from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mase.privacy import is_sensitive_key, redact_value

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[2]


def resolve_audit_log_path() -> Path:
    raw_path = str(os.environ.get("MASE_AUDIT_LOG_PATH") or "").strip()
    return Path(raw_path).expanduser().resolve() if raw_path else (ROOT / "memory" / "audit.jsonl").resolve()


def sanitize_audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if is_sensitive_key(str(key)) else sanitize_audit_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_audit_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_audit_value(item) for item in value]
    if isinstance(value, str):
        redacted = redact_value(value)
        return f"{redacted[:500]}...[truncated]" if len(redacted) > 500 else redacted
    return redact_value(value)


def append_audit_event(
    *,
    actor_id: str,
    role: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    outcome: str = "success",
    scope: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    event = {
        "audit_id": uuid.uuid4().hex,
        "created_at": datetime.now(UTC).isoformat(),
        "actor_id": actor_id,
        "role": role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "outcome": outcome,
        "scope": sanitize_audit_value(scope or {}),
        "metadata": sanitize_audit_value(metadata or {}),
    }
    audit_path = path or resolve_audit_log_path()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def list_audit_events(
    *,
    limit: int = 100,
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    audit_path = path or resolve_audit_log_path()
    metadata: dict[str, Any] = {
        "path": str(audit_path),
        "exists": audit_path.exists(),
        "skipped_count": 0,
        "skipped_lines": [],
    }
    if not audit_path.exists():
        return {"events": [], "metadata": metadata}
    events: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(audit_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            metadata["skipped_count"] += 1
            metadata["skipped_lines"].append(line_number)
            continue
        if actor_id and event.get("actor_id") != actor_id:
            continue
        if action and event.get("action") != action:
            continue
        if resource_type and event.get("resource_type") != resource_type:
            continue
        events.append(event)
    return {"events": list(reversed(events))[: max(1, min(int(limit), 500))], "metadata": metadata}


__all__ = [
    "append_audit_event",
    "list_audit_events",
    "resolve_audit_log_path",
    "sanitize_audit_value",
]
