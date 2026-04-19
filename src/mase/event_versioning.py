from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

ACTIVE_STATUS = "active"
DEPRECATED_STATUS = "deprecated"


def _parse_timestamp(raw_value: Any) -> datetime | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _logical_event_key(event: Mapping[str, Any], index: int) -> str:
    logical_event_id = str(event.get("logical_event_id") or "").strip()
    if logical_event_id:
        return logical_event_id
    event_id = str(event.get("event_id") or "").strip()
    if event_id:
        return event_id
    event_type = str(event.get("event_type") or "generic").strip().lower() or "generic"
    normalized_name = str(event.get("normalized_name") or event.get("display_name") or event.get("source") or "").strip().lower()
    return f"{event_type}:{normalized_name or index}"


def _event_sort_key(event: Mapping[str, Any]) -> tuple[int, datetime, str, str]:
    parsed_timestamp = _parse_timestamp(event.get("timestamp"))
    raw_timestamp = str(event.get("timestamp") or "").strip()
    event_id = str(event.get("event_id") or "").strip()
    if parsed_timestamp is not None:
        return (0, parsed_timestamp, raw_timestamp, event_id)
    return (1, datetime.min, raw_timestamp, event_id)


def resolve_event_versions(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, raw_event in enumerate(events):
        event = dict(raw_event)
        logical_event_id = _logical_event_key(event, index)
        event["logical_event_id"] = logical_event_id
        event["event_id"] = str(event.get("event_id") or f"{logical_event_id}::v{index}")
        groups[logical_event_id].append(event)

    resolved: list[dict[str, Any]] = []
    for logical_event_id, group in groups.items():
        ordered = sorted(group, key=_event_sort_key)
        version_count = len(ordered)
        for version_index, event in enumerate(ordered):
            successor = ordered[version_index + 1] if version_index + 1 < version_count else None
            event["logical_event_id"] = logical_event_id
            event["version_index"] = version_index
            event["version_count"] = version_count
            event["status"] = ACTIVE_STATUS if successor is None else DEPRECATED_STATUS
            event["deprecated_by"] = str(successor.get("event_id") or "") if successor else ""
            resolved.append(event)
    resolved.sort(key=_event_sort_key, reverse=True)
    return resolved


def filter_active_events(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(event) for event in events if str(event.get("status") or "").strip().lower() == ACTIVE_STATUS]


def build_event_version_views(events: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    views: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in resolve_event_versions(events):
        logical_event_id = str(event.get("logical_event_id") or "").strip()
        if not logical_event_id:
            continue
        grouped[logical_event_id].append(event)

    for logical_event_id, group in grouped.items():
        history = sorted(group, key=_event_sort_key)
        current = history[-1] if history else None
        previous = history[-2] if len(history) >= 2 else None
        views[logical_event_id] = {
            "logical_event_id": logical_event_id,
            "current": current,
            "previous": previous,
            "history": history,
            "active": [event for event in history if str(event.get("status") or "").strip().lower() == ACTIVE_STATUS],
            "deprecated": [event for event in history if str(event.get("status") or "").strip().lower() == DEPRECATED_STATUS],
        }
    return views


def get_event_version_view(events: Iterable[Mapping[str, Any]], logical_event_id: str) -> dict[str, Any]:
    return build_event_version_views(events).get(str(logical_event_id or "").strip(), {})
