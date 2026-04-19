from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from event_versioning import ACTIVE_STATUS, resolve_event_versions

EVENT_BUS_FILE_NAME = "event-bus-latest.json"
EVENT_BUS_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1


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


def _normalize_text_token(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _normalize_event_name(text: str) -> str:
    return _normalize_text_token(text)


def _normalize_source_signature(text: str) -> str:
    return _normalize_text_token(text)[:160]


def _compact_display_name(text: str, fallback: str) -> str:
    source = str(text or "").strip()
    if source:
        return source[:96]
    return str(fallback or "").strip()[:96]


def _merge_scope_hints(*groups: dict[str, Any] | None) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {"months": [], "weekdays": [], "locations": []}
    for group in groups:
        if not isinstance(group, dict):
            continue
        for key in merged:
            merged[key] = _dedupe_strings(
                [
                    *merged[key],
                    *[str(item) for item in group.get(key, []) if str(item).strip()],
                ]
            )
    return merged


def _normalize_scope_hints(scope_hints: dict[str, Any] | None) -> dict[str, list[str]]:
    hints = scope_hints if isinstance(scope_hints, dict) else {}
    return {
        "months": _dedupe_strings([str(item) for item in hints.get("months", []) if str(item).strip()]),
        "weekdays": _dedupe_strings([str(item) for item in hints.get("weekdays", []) if str(item).strip()]),
        "locations": _dedupe_strings([str(item) for item in hints.get("locations", []) if str(item).strip()]),
    }


def _scope_hints_from_attributes(attributes: dict[str, Any] | None) -> dict[str, list[str]]:
    if not isinstance(attributes, dict):
        return {"months": [], "weekdays": [], "locations": []}
    months: list[str] = []
    weekdays: list[str] = []
    locations: list[str] = []
    for key in ("month", "months"):
        value = attributes.get(key)
        if isinstance(value, list):
            months.extend(str(item) for item in value if str(item).strip())
        elif str(value or "").strip():
            months.append(str(value))
    for key in ("weekday", "weekdays"):
        value = attributes.get(key)
        if isinstance(value, list):
            weekdays.extend(str(item) for item in value if str(item).strip())
        elif str(value or "").strip():
            weekdays.append(str(value))
    for key in ("location", "locations", "place", "store", "venue"):
        value = attributes.get(key)
        if isinstance(value, list):
            locations.extend(str(item) for item in value if str(item).strip())
        elif str(value or "").strip():
            locations.append(str(value))
    return _normalize_scope_hints({"months": months, "weekdays": weekdays, "locations": locations})


def _entities_from_card_event(event_card: dict[str, Any], base_entities: list[str], card_segments: list[dict[str, Any]]) -> list[str]:
    return _dedupe_strings(
        [
            *base_entities,
            str(event_card.get("display_name") or ""),
            str(event_card.get("normalized_name") or ""),
            *[
                str(entity)
                for segment in card_segments
                for entity in segment.get("entities", [])
                if str(entity).strip()
            ],
        ]
    )[:12]


def _build_logical_event_id(event_type: str, normalized_name: str, entities: list[str], scope_hints: dict[str, list[str]]) -> str:
    normalized_entities = [_normalize_text_token(item) for item in entities[:4] if _normalize_text_token(item)]
    normalized_scope = [
        *[_normalize_text_token(item) for item in scope_hints.get("months", [])[:2]],
        *[_normalize_text_token(item) for item in scope_hints.get("locations", [])[:2]],
    ]
    return "|".join(
        [
            str(event_type or "generic").strip().lower() or "generic",
            normalized_name or "event",
            ",".join(sorted(normalized_entities)),
            ",".join(sorted(item for item in normalized_scope if item)),
        ]
    )


def _build_dedupe_key(logical_event_id: str, source_signature: str, timestamp: str) -> str:
    return "|".join(
        [
            str(logical_event_id or "").strip(),
            str(source_signature or "").strip(),
            str(timestamp or "").strip(),
        ]
    )


def _build_event_payload(
    fact_card: dict[str, Any],
    *,
    provenance: str,
    index: int,
    event_type: str,
    display_name: str,
    source: str,
    entities: list[str],
    scope_hints: dict[str, list[str]],
    polarity: str,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record_path = str(fact_card.get("record_path") or "")
    timestamp = str(fact_card.get("timestamp") or "")
    time_anchor = fact_card.get("time_anchor", {}) if isinstance(fact_card.get("time_anchor"), dict) else {}
    normalized_scope_hints = _normalize_scope_hints(
        _merge_scope_hints(
            scope_hints,
            {
                "months": [str(time_anchor.get("month") or "")],
                "weekdays": [str(time_anchor.get("weekday") or "")],
                "locations": [],
            },
            _scope_hints_from_attributes(attributes),
        )
    )
    normalized_name = _normalize_event_name(display_name or source)
    normalized_entities = _dedupe_strings(entities)[:12]
    source_signature = _normalize_source_signature(source or display_name)
    logical_event_id = _build_logical_event_id(
        str(event_type or "generic").strip() or "generic",
        normalized_name or source_signature,
        normalized_entities,
        normalized_scope_hints,
    )
    dedupe_key = _build_dedupe_key(logical_event_id, source_signature, timestamp)
    event_id = f"{record_path}::{provenance}:{index}"
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "logical_event_id": logical_event_id,
        "dedupe_key": dedupe_key,
        "source_signature": source_signature,
        "event_type": str(event_type or "generic").strip() or "generic",
        "display_name": _compact_display_name(display_name, source),
        "normalized_name": normalized_name,
        "timestamp": timestamp,
        "thread_id": str(time_anchor.get("thread_id") or ""),
        "thread_label": str(time_anchor.get("thread_label") or ""),
        "entities": normalized_entities,
        "scope_hints": normalized_scope_hints,
        "source": str(source or "").strip()[:320],
        "polarity": "negative" if str(polarity or "").lower() == "negative" else "positive",
        "attributes": dict(attributes or {}),
        "record_path": record_path,
        "status": ACTIVE_STATUS,
        "deprecated_by": "",
        "provenance": provenance,
    }


def _normalize_event_record(raw_event: dict[str, Any], *, index: int) -> dict[str, Any]:
    event = dict(raw_event)
    event_type = str(event.get("event_type") or "generic").strip() or "generic"
    display_name = str(event.get("display_name") or event.get("normalized_name") or event.get("source") or "").strip()
    source = str(event.get("source") or display_name).strip()
    scope_hints = _normalize_scope_hints(event.get("scope_hints") if isinstance(event.get("scope_hints"), dict) else {})
    attributes = event.get("attributes")
    if not isinstance(attributes, dict):
        values = event.get("values")
        attributes = dict(values) if isinstance(values, dict) else {}
    entities = _dedupe_strings([str(item) for item in event.get("entities", []) if str(item).strip()])
    normalized_name = _normalize_event_name(str(event.get("normalized_name") or display_name or source))
    source_signature = _normalize_source_signature(str(event.get("source_signature") or source))
    logical_event_id = str(event.get("logical_event_id") or "").strip()
    if not logical_event_id:
        logical_event_id = _build_logical_event_id(event_type, normalized_name or source_signature, entities, scope_hints)
    timestamp = str(event.get("timestamp") or "").strip()
    dedupe_key = str(event.get("dedupe_key") or "").strip() or _build_dedupe_key(logical_event_id, source_signature, timestamp)
    event_id = str(event.get("event_id") or "").strip() or f"{logical_event_id}::normalized:{index}"
    status = str(event.get("status") or ACTIVE_STATUS).strip().lower() or ACTIVE_STATUS
    if status not in {ACTIVE_STATUS, "deprecated"}:
        status = ACTIVE_STATUS
    return {
        "schema_version": int(event.get("schema_version") or EVENT_SCHEMA_VERSION),
        "event_id": event_id,
        "logical_event_id": logical_event_id,
        "dedupe_key": dedupe_key,
        "source_signature": source_signature,
        "event_type": event_type,
        "display_name": _compact_display_name(display_name, source),
        "normalized_name": normalized_name,
        "timestamp": timestamp,
        "thread_id": str(event.get("thread_id") or "").strip(),
        "thread_label": str(event.get("thread_label") or "").strip(),
        "entities": entities,
        "scope_hints": scope_hints,
        "source": source[:320],
        "polarity": "negative" if str(event.get("polarity") or "").lower() == "negative" else "positive",
        "attributes": attributes,
        "record_path": str(event.get("record_path") or "").strip(),
        "status": status,
        "deprecated_by": str(event.get("deprecated_by") or "").strip(),
        "provenance": str(event.get("provenance") or "unknown").strip() or "unknown",
    }


def build_events_from_fact_card(fact_card: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(fact_card, dict):
        return []
    base_entities = [str(item) for item in fact_card.get("entities", []) if str(item).strip()]
    base_scope = fact_card.get("scope_hints", {}) if isinstance(fact_card.get("scope_hints"), dict) else {}
    event_type = str(fact_card.get("event_type") or "generic").strip() or "generic"
    attributes = fact_card.get("attributes", {}) if isinstance(fact_card.get("attributes"), dict) else {}
    event_cards = [item for item in attributes.get("event_cards", []) if isinstance(item, dict)]
    event_segments = [item for item in fact_card.get("event_segments", []) if isinstance(item, dict)]
    events: list[dict[str, Any]] = []

    for index, event_card in enumerate(event_cards):
        card_segments = [item for item in event_card.get("event_segments", []) if isinstance(item, dict)]
        card_attributes = (
            dict(event_card.get("attributes"))
            if isinstance(event_card.get("attributes"), dict)
            else dict(event_card.get("values"))
            if isinstance(event_card.get("values"), dict)
            else {}
        )
        card_scope = _merge_scope_hints(
            base_scope,
            event_card.get("scope_hints") if isinstance(event_card.get("scope_hints"), dict) else {},
            _scope_hints_from_attributes(card_attributes),
            *[
                segment.get("scope_hints")
                for segment in card_segments
                if isinstance(segment.get("scope_hints"), dict)
            ],
        )
        events.append(
            _build_event_payload(
                fact_card,
                provenance="event_card",
                index=index,
                event_type=str(event_card.get("event_type") or event_type),
                display_name=str(event_card.get("display_name") or event_card.get("normalized_name") or ""),
                source=str(event_card.get("source") or fact_card.get("resolved_source_span") or ""),
                entities=_entities_from_card_event(event_card, base_entities, card_segments),
                scope_hints=card_scope,
                polarity=str(event_card.get("polarity") or fact_card.get("polarity") or "positive"),
                attributes=card_attributes,
            )
        )

    for index, segment in enumerate(event_segments):
        source = str(segment.get("resolved_text") or segment.get("text") or "").strip()
        if not source:
            continue
        segment_entities = _dedupe_strings(
            [*base_entities, *[str(item) for item in segment.get("entities", []) if str(item).strip()]]
        )
        display_name = segment_entities[0] if segment_entities else source
        events.append(
            _build_event_payload(
                fact_card,
                provenance="event_segment",
                index=index,
                event_type=event_type,
                display_name=display_name,
                source=source,
                entities=segment_entities,
                scope_hints=_merge_scope_hints(
                    base_scope,
                    segment.get("scope_hints") if isinstance(segment.get("scope_hints"), dict) else {},
                ),
                polarity=str(segment.get("polarity") or fact_card.get("polarity") or "positive"),
            )
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, event in enumerate(events):
        normalized = _normalize_event_record(event, index=index)
        marker = str(normalized.get("dedupe_key") or "")
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(normalized)
    return deduped[:24]


def _normalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_event_record(event, index=index) for index, event in enumerate(events) if isinstance(event, dict)]
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in normalized:
        marker = str(event.get("dedupe_key") or "")
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(event)
    return deduped


def build_event_bus_snapshot(cards: list[dict[str, Any]]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        card_events = [item for item in card.get("events", []) if isinstance(item, dict)]
        events.extend(card_events or build_events_from_fact_card(card))
    resolved_events = resolve_event_versions(_normalize_events(events))
    entity_counts: dict[str, int] = {}
    for event in resolved_events:
        for entity in event.get("entities", []):
            lowered = str(entity).strip().lower()
            if not lowered:
                continue
            entity_counts[lowered] = entity_counts.get(lowered, 0) + 1
    return {
        "schema_version": EVENT_BUS_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "event_count": len(resolved_events),
        "active_event_count": sum(1 for event in resolved_events if str(event.get("status") or "") == ACTIVE_STATUS),
        "logical_event_count": len({str(event.get("logical_event_id") or "") for event in resolved_events if str(event.get("logical_event_id") or "").strip()}),
        "top_entities": [
            {"entity": entity, "count": count}
            for entity, count in sorted(entity_counts.items(), key=lambda item: (-item[1], item[0]))[:200]
        ],
        "events": resolved_events[:2000],
    }


def load_event_bus_snapshot(path: str | Path) -> dict[str, Any]:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return build_event_bus_snapshot([])
    with snapshot_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        return build_event_bus_snapshot([])
    events = [item for item in payload.get("events", []) if isinstance(item, dict)]
    snapshot = build_event_bus_snapshot([{"events": events}])
    generated_at = str(payload.get("generated_at") or "").strip()
    if generated_at:
        snapshot["generated_at"] = generated_at
    return snapshot


def query_event_bus(
    snapshot_or_path: dict[str, Any] | str | Path,
    *,
    entities: list[str] | None = None,
    event_types: list[str] | None = None,
    months: list[str] | None = None,
    locations: list[str] | None = None,
    thread_id: str | None = None,
    active_only: bool = True,
    limit: int = 20,
) -> list[dict[str, Any]]:
    snapshot = (
        load_event_bus_snapshot(snapshot_or_path)
        if isinstance(snapshot_or_path, (str, Path))
        else build_event_bus_snapshot([{"events": snapshot_or_path.get("events", [])}])
        if isinstance(snapshot_or_path, dict)
        else build_event_bus_snapshot([])
    )
    events = [item for item in snapshot.get("events", []) if isinstance(item, dict)]
    normalized_entities = [_normalize_text_token(str(item)) for item in (entities or []) if str(item).strip()]
    normalized_types = {_normalize_text_token(str(item)) for item in (event_types or []) if str(item).strip()}
    normalized_months = {_normalize_text_token(str(item)) for item in (months or []) if str(item).strip()}
    normalized_locations = {_normalize_text_token(str(item)) for item in (locations or []) if str(item).strip()}
    normalized_thread_id = str(thread_id or "").strip()
    ranked: list[tuple[int, dict[str, Any]]] = []
    for event in events:
        if active_only and str(event.get("status") or "").strip().lower() != ACTIVE_STATUS:
            continue
        if normalized_types and _normalize_text_token(str(event.get("event_type") or "")) not in normalized_types:
            continue
        if normalized_thread_id and str(event.get("thread_id") or "").strip() != normalized_thread_id:
            continue

        score = 0
        event_entities = [_normalize_text_token(str(item)) for item in event.get("entities", []) if str(item).strip()]
        event_source = _normalize_text_token(str(event.get("source") or ""))
        display_name = _normalize_text_token(str(event.get("display_name") or ""))
        if normalized_entities:
            matched_entity = False
            for entity in normalized_entities:
                if not entity:
                    continue
                if entity in event_entities or entity in event_source or entity in display_name:
                    score += 40
                    matched_entity = True
            if not matched_entity:
                continue
        scope_hints = event.get("scope_hints", {}) if isinstance(event.get("scope_hints"), dict) else {}
        event_months = {_normalize_text_token(str(item)) for item in scope_hints.get("months", []) if str(item).strip()}
        event_locations = {_normalize_text_token(str(item)) for item in scope_hints.get("locations", []) if str(item).strip()}
        if normalized_months:
            if not event_months.intersection(normalized_months):
                continue
            score += 12
        if normalized_locations:
            matched_location = False
            for location in normalized_locations:
                if any(location == item or location in item or item in location for item in event_locations if item):
                    matched_location = True
                    score += 12
                    break
            if not matched_location:
                continue
        if str(event.get("status") or "").strip().lower() == ACTIVE_STATUS:
            score += 4
        if str(event.get("polarity") or "").strip().lower() == "negative":
            score -= 6
        ranked.append((score, event))

    ranked.sort(key=lambda item: (item[0], str(item[1].get("timestamp") or ""), str(item[1].get("event_id") or "")), reverse=True)
    return [event for _, event in ranked[: max(1, int(limit or 20))]]


__all__ = [
    "EVENT_BUS_FILE_NAME",
    "EVENT_BUS_SCHEMA_VERSION",
    "EVENT_SCHEMA_VERSION",
    "build_event_bus_snapshot",
    "build_events_from_fact_card",
    "load_event_bus_snapshot",
    "query_event_bus",
]
