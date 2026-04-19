from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from event_bus import EVENT_BUS_FILE_NAME, build_event_bus_snapshot, build_events_from_fact_card

SYSTEM_DIR_NAME = "system"
ENGLISH_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
ENGLISH_WEEKDAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}
NEGATIVE_EVENT_PATTERNS = [
    r"\bdid not\b",
    r"\bdidn't\b",
    r"\bnever\b",
    r"\bwas not able to\b",
    r"\bwasn't able to\b",
    r"\bcould not\b",
    r"\bcouldn't\b",
    r"\bdid not attend\b",
    r"\bdidn't attend\b",
    r"\bdid not go\b",
    r"\bdidn't go\b",
    r"\bskipped\b",
    r"\bskip(?:ped)?\b",
    r"\bmissed\b",
    r"\bcancelled\b",
    r"\bcanceled\b",
]
EVENT_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+|;\s+")
EVENT_CONTINUATION_PATTERN = re.compile(
    r"\s+(?:and then|then|afterward|after that|later that day|later|also)\s+(?=(?:i|we|my|our|[A-Z]))",
    re.IGNORECASE,
)


def fact_card_path_for_record(record_path: str | Path) -> Path:
    path = Path(record_path)
    if path.suffix.lower() == ".json":
        return path.with_name(f"{path.stem}.fact_card.json")
    return Path(f"{path}.fact_card.json")


def load_fact_card(card_path: str | Path) -> dict[str, Any]:
    path = Path(card_path)
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return payload if isinstance(payload, dict) else {}


def list_fact_card_files(memory_dir: str | Path, date_hint: str | None = None) -> list[Path]:
    root = Path(memory_dir)
    if not root.exists():
        return []
    if date_hint:
        target_dir = root / date_hint
        if not target_dir.exists():
            return []
        return sorted(target_dir.glob("*.fact_card.json"), reverse=True)
    files = [path for path in root.rglob("*.fact_card.json") if SYSTEM_DIR_NAME not in path.parts]
    return sorted(files, reverse=True)


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


def _scope_hint_values(source: dict[str, list[str]] | None, key: str) -> list[str]:
    return [str(item) for item in (source or {}).get(key, []) if str(item).strip()]


def _card_field_values(cards: list[dict[str, Any]], field: str) -> list[str]:
    return [str(item.get(field) or "") for item in cards if isinstance(item, dict)]


def _parse_timestamp(raw_value: str) -> datetime | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _extract_explicit_entities(text: str, candidate_entities: list[str]) -> list[str]:
    source = str(text or "")
    explicit: list[str] = []
    noise_tokens = {
        "i",
        "i m",
        "i ve",
        "i ll",
        "we",
        "we re",
        "how",
        "what",
        "when",
        "where",
        "why",
        "which",
        "who",
        "can",
        "could",
        "would",
        "should",
        "some",
        "think",
        "actually",
        "just",
        "really",
        "any",
        "the",
        "a",
        "an",
    }

    def _is_noise_entity(value: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
        return not normalized or normalized in noise_tokens

    for entity in candidate_entities:
        normalized = str(entity or "").strip()
        if normalized and not _is_noise_entity(normalized) and normalized.lower() in source.lower():
            explicit.append(normalized)
    for phrase in re.findall(r"\b(?:[A-Z][A-Za-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-z]+|[A-Z]{2,})){0,2}\b", source):
        cleaned = phrase.strip()
        if cleaned not in {"I", "We", "The", "A", "An"} and not _is_noise_entity(cleaned):
            explicit.append(cleaned)
    return _dedupe_strings(explicit)


def _looks_like_meta_answer_contamination(text: str) -> bool:
    source = str(text or "").strip()
    if not source:
        return False
    return bool(
        re.search(
            r"^\s*(?:based on|according to) the provided evidence\b"
            r"|^\s*the provided evidence\b"
            r"|^\s*you did not mention\b"
            r"|^\s*(?:it is |it's )?not explicitly (?:mentioned|stated)\b"
            r"|^\s*i do not have enough information\b"
            r"|^\s*when you just started\b.*\bnow,\s*you\b"
            r"|^\s*previously,\b.*\bnow,\b",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def resolve_coreferences_text(text: str, entities: list[str] | None = None) -> str:
    candidate_entities = _dedupe_strings([str(item) for item in (entities or []) if str(item).strip()])
    sentences = [part.strip() for part in EVENT_SPLIT_PATTERN.split(str(text or "")) if part.strip()]
    if not sentences:
        return str(text or "")

    resolved_sentences: list[str] = []
    last_singular = candidate_entities[0] if candidate_entities else ""
    last_plural = ""
    for sentence in sentences:
        explicit_entities = _extract_explicit_entities(sentence, candidate_entities)
        if explicit_entities:
            chosen = explicit_entities[-1]
            if " and " in chosen.lower() or chosen.lower().endswith("s"):
                last_plural = chosen
            else:
                last_singular = chosen
        resolved = sentence
        if last_singular:
            resolved = re.sub(r"\b(it|that)\b", last_singular, resolved, flags=re.IGNORECASE)
            resolved = re.sub(
                r"\bthis\b(?!\s+(?:year|month|week|day|night|morning|afternoon|evening|season|time)\b)",
                last_singular,
                resolved,
                flags=re.IGNORECASE,
            )
        plural_reference = last_plural or last_singular
        if plural_reference:
            resolved = re.sub(r"\b(they|them|their|these|those)\b", plural_reference, resolved, flags=re.IGNORECASE)
        resolved_sentences.append(resolved)
        explicit_after_resolution = _extract_explicit_entities(resolved, candidate_entities)
        if explicit_after_resolution:
            chosen = explicit_after_resolution[-1]
            if " and " in chosen.lower() or chosen.lower().endswith("s"):
                last_plural = chosen
            else:
                last_singular = chosen
    return " ".join(resolved_sentences).strip()


def detect_negative_polarity(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(re.search(pattern, lowered) for pattern in NEGATIVE_EVENT_PATTERNS)


def _merge_scope_hints(
    base: dict[str, list[str]] | None,
    extra: dict[str, list[str]] | None,
    *,
    inherit_singletons: bool = True,
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {"months": [], "weekdays": [], "locations": []}
    for key in merged:
        extra_values = _scope_hint_values(extra, key)
        base_values = _scope_hint_values(base, key)
        if extra_values:
            merged[key] = _dedupe_strings(extra_values + base_values)
        elif inherit_singletons and len(base_values) <= 1:
            merged[key] = _dedupe_strings(base_values)
    return merged


def extract_event_segments_from_text(
    text: str,
    entities: list[str] | None = None,
    inherited_scope: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    resolved = resolve_coreferences_text(text, entities)
    raw_segments: list[str] = []
    for sentence in [part.strip() for part in EVENT_SPLIT_PATTERN.split(resolved) if part.strip()]:
        clauses = [part.strip(" ,") for part in EVENT_CONTINUATION_PATTERN.split(sentence) if part.strip(" ,")]
        raw_segments.extend(clauses or [sentence])

    segments: list[dict[str, Any]] = []
    for segment in raw_segments:
        scope_hints = _merge_scope_hints(inherited_scope, _extract_scope_hints_from_text(segment))
        explicit_entities = _extract_explicit_entities(segment, list(entities or []))
        segments.append(
            {
                "text": segment,
                "resolved_text": segment,
                "scope_hints": scope_hints,
                "entities": explicit_entities[:6],
                "polarity": "negative" if detect_negative_polarity(segment) else "positive",
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for segment in segments:
        key = str(segment.get("resolved_text") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(segment)
    return deduped[:12]


def _extract_scope_hints_from_text(text: str) -> dict[str, list[str]]:
    source = str(text or "")
    lowered = source.lower()
    months = [month for month in ENGLISH_MONTHS if month in lowered]
    for month_number, month_name in enumerate(ENGLISH_MONTHS, start=1):
        if re.search(rf"\b{month_number}/\d{{1,2}}\b", lowered):
            months.append(month_name)
    weekdays = [day for day in ENGLISH_WEEKDAYS if day in lowered]
    locations: list[str] = []
    for span in re.findall(
        r"\b(?:in|at|to|from|near|around)\s+((?:[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})(?:\s+(?:and|,)\s+(?:[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2}))*)",
        source,
    ):
        locations.extend(part.strip() for part in re.split(r"\s+(?:and|,)\s+", span) if part.strip())
    return {
        "months": _dedupe_strings(months),
        "weekdays": _dedupe_strings(weekdays),
        "locations": _dedupe_strings(locations),
    }


def _build_scope_hints(record: dict[str, Any], memory_profile: dict[str, Any], timestamp: str) -> dict[str, list[str]]:
    source_parts = [
        str(record.get("user_query") or ""),
        "" if _looks_like_meta_answer_contamination(record.get("assistant_response")) else str(record.get("assistant_response") or ""),
        str(record.get("semantic_summary") or ""),
    ]
    for event_card in memory_profile.get("event_cards", []) if isinstance(memory_profile, dict) else []:
        if isinstance(event_card, dict):
            if not _looks_like_meta_answer_contamination(event_card.get("source")):
                source_parts.append(str(event_card.get("source") or ""))
            if not _looks_like_meta_answer_contamination(event_card.get("display_name")):
                source_parts.append(str(event_card.get("display_name") or ""))
    combined = "\n".join(part for part in source_parts if part.strip())
    hints = _extract_scope_hints_from_text(combined)
    parsed = _parse_timestamp(timestamp)
    if parsed is not None:
        combined_lower = combined.lower()
        relative_time_signal = bool(
            re.search(
                r"\b(?:last|this|next|ago|today|yesterday|tomorrow|recent|recently|past|upcoming)\b",
                combined_lower,
            )
        )
        if relative_time_signal or not hints.get("months"):
            hints["months"] = _dedupe_strings([*hints.get("months", []), parsed.strftime("%B").lower()])
        if relative_time_signal or not hints.get("weekdays"):
            hints["weekdays"] = _dedupe_strings([*hints.get("weekdays", []), parsed.strftime("%A").lower()])
    return hints


def _event_type_from_profile(memory_profile: dict[str, Any]) -> str:
    event_cards = memory_profile.get("event_cards", [])
    if isinstance(event_cards, list) and event_cards:
        first = event_cards[0]
        if isinstance(first, dict):
            return str(first.get("event_type") or "generic").strip() or "generic"
    return "generic"


def _state_entries_from_profile(memory_profile: dict[str, Any], entities: list[str], timestamp: str, record_path: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    event_cards = memory_profile.get("event_cards", []) if isinstance(memory_profile, dict) else []
    numeric_cards = memory_profile.get("numeric_cards", []) if isinstance(memory_profile, dict) else []
    primary_entities = entities[:2] or ["memory"]
    for card in numeric_cards[:8]:
        if not isinstance(card, dict):
            continue
        if _looks_like_meta_answer_contamination(card.get("source")):
            continue
        entries.append(
            {
                "entity": primary_entities[0],
                "attribute": str(card.get("kind") or "numeric"),
                "value": str(card.get("value") or ""),
                "source": str(card.get("source") or ""),
                "timestamp": timestamp,
                "record_path": record_path,
            }
        )
    for card in event_cards[:8]:
        if not isinstance(card, dict):
            continue
        if _looks_like_meta_answer_contamination(card.get("source")) or _looks_like_meta_answer_contamination(card.get("display_name")):
            continue
        entries.append(
            {
                "entity": str(card.get("display_name") or primary_entities[0]),
                "attribute": str(card.get("event_type") or "event"),
                "value": str(card.get("display_name") or ""),
                "source": str(card.get("source") or ""),
                "timestamp": timestamp,
                "record_path": record_path,
            }
        )
    return entries


def build_fact_card(record: dict[str, Any], record_path: str | Path) -> dict[str, Any]:
    memory_profile = record.get("memory_profile", {})
    if not isinstance(memory_profile, dict):
        memory_profile = {}
    entities = _dedupe_strings(
        [
            *[str((card or {}).get("name") or "") for card in memory_profile.get("entity_cards", []) if isinstance(card, dict)],
            *[str(item) for item in record.get("key_entities", [])],
        ]
    )
    entities = [
        item
        for item in entities
        if re.sub(r"[^a-z0-9]+", " ", str(item or "").lower()).strip()
        not in {"i", "i m", "i ve", "i ll", "we", "we re", "can", "could", "would", "should", "some", "think"}
    ][:12]
    relations = [card for card in memory_profile.get("relation_cards", []) if isinstance(card, dict)][:8]
    attributes = {
        "keywords": [str(item) for item in memory_profile.get("keywords", [])][:16],
        "numeric_cards": [
            card
            for card in memory_profile.get("numeric_cards", [])
            if isinstance(card, dict) and not _looks_like_meta_answer_contamination(card.get("source"))
        ][:12],
        "event_cards": [
            card
            for card in memory_profile.get("event_cards", [])
            if isinstance(card, dict)
            and not _looks_like_meta_answer_contamination(card.get("source"))
            and not _looks_like_meta_answer_contamination(card.get("display_name"))
        ][:12],
        "topic_tokens": [str(item) for item in record.get("topic_tokens", [])][:8],
    }
    timestamp = str(record.get("timestamp") or "")
    scope_hints = _build_scope_hints(record, memory_profile, timestamp)
    source_candidates = [
        str(record.get("user_query") or ""),
        "" if _looks_like_meta_answer_contamination(record.get("assistant_response")) else str(record.get("assistant_response") or ""),
        str(record.get("semantic_summary") or ""),
    ]
    source_span = next((part[:420] for part in source_candidates if str(part).strip()), "")
    resolved_source_span = resolve_coreferences_text(source_span, entities)
    event_segments = extract_event_segments_from_text(
        resolved_source_span,
        entities,
        inherited_scope=scope_hints,
    )
    enriched_event_cards: list[dict[str, Any]] = []
    for card in attributes["event_cards"]:
        enriched = dict(card)
        if "polarity" not in enriched:
            enriched["polarity"] = "negative" if detect_negative_polarity(str(enriched.get("source") or "")) else "positive"
        if "event_segments" not in enriched:
            enriched["event_segments"] = extract_event_segments_from_text(
                str(enriched.get("source") or ""),
                [str(enriched.get("display_name") or ""), *entities],
                inherited_scope=scope_hints,
            )
        enriched_event_cards.append(enriched)
    attributes["event_cards"] = enriched_event_cards[:12]
    state_entries = _state_entries_from_profile(memory_profile, entities, timestamp, str(record_path))
    confidence_score = min(
        0.98,
        0.35
        + min(0.25, len(entities) * 0.04)
        + min(0.2, len(attributes["numeric_cards"]) * 0.03)
        + min(0.15, len(attributes["event_cards"]) * 0.04)
        + min(0.08, len(event_segments) * 0.01)
        + (0.08 if relations else 0.0),
    )
    confidence = {
        "score": round(confidence_score, 3),
        "reason_codes": _dedupe_strings(
            [
                "entities" if entities else "",
                "numeric_cards" if attributes["numeric_cards"] else "",
                "event_cards" if attributes["event_cards"] else "",
                "relations" if relations else "",
            ]
        ),
    }
    fact_card = {
        "schema_version": 3,
        "record_path": str(record_path),
        "timestamp": timestamp,
        "language": str(record.get("language") or ""),
        "time_anchor": {
            "timestamp": timestamp,
            "date": timestamp.split("T", 1)[0] if "T" in timestamp else "",
            "month": scope_hints.get("months", [])[0] if scope_hints.get("months") else "",
            "weekday": scope_hints.get("weekdays", [])[0] if scope_hints.get("weekdays") else "",
            "thread_id": record.get("thread_id"),
            "thread_label": record.get("thread_label"),
        },
        "event_type": _event_type_from_profile(memory_profile),
        "entities": entities,
        "scope_hints": scope_hints,
        "attributes": attributes,
        "relations": relations,
        "source_span": source_span,
        "resolved_source_span": resolved_source_span,
        "event_segments": event_segments,
        "polarity": "negative" if any(segment.get("polarity") == "negative" for segment in event_segments) else "positive",
        "confidence": confidence,
        "current_state": state_entries[:8],
        "state_history": state_entries[:8],
    }
    fact_card["events"] = build_events_from_fact_card(fact_card)
    return fact_card


def write_fact_card_sidecar(record_path: str | Path, record: dict[str, Any]) -> str:
    card_path = fact_card_path_for_record(record_path)
    card_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_fact_card(record, record_path)
    with card_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return str(card_path)


def refresh_memory_sidecars(memory_dir: str | Path, lookback_days: int = 7) -> dict[str, str]:
    root = Path(memory_dir)
    root.mkdir(parents=True, exist_ok=True)
    system_dir = root / SYSTEM_DIR_NAME
    system_dir.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now() - timedelta(days=max(1, lookback_days))
    cards: list[dict[str, Any]] = []
    for card_path in list_fact_card_files(root):
        payload = load_fact_card(card_path)
        timestamp = _parse_timestamp(payload.get("timestamp") or "")
        if timestamp is None or timestamp >= cutoff:
            cards.append(payload)
    cards.sort(key=lambda item: str(item.get("timestamp") or ""))

    entity_clusters: dict[str, dict[str, Any]] = {}
    state_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    current_state: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    event_chains: dict[str, list[dict[str, Any]]] = defaultdict(list)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_seen: set[str] = set()
    edge_seen: set[str] = set()

    for card in cards:
        timestamp = str(card.get("timestamp") or "")
        event_type = str(card.get("event_type") or "generic")
        entities = [str(item) for item in card.get("entities", []) if str(item).strip()]
        relations = [item for item in card.get("relations", []) if isinstance(item, dict)]
        attribute_cards = card.get("attributes", {}) if isinstance(card.get("attributes"), dict) else {}
        numeric_cards = [item for item in attribute_cards.get("numeric_cards", []) if isinstance(item, dict)]
        event_cards = [item for item in attribute_cards.get("event_cards", []) if isinstance(item, dict)]

        event_node_id = f"event:{card.get('record_path')}"
        if event_node_id not in node_seen:
            node_seen.add(event_node_id)
            nodes.append({"id": event_node_id, "kind": "event", "label": event_type, "timestamp": timestamp})

        for entity in entities:
            normalized = entity.lower()
            cluster = entity_clusters.setdefault(
                normalized,
                {"canonical_entity": entity, "aliases": [], "record_count": 0, "event_types": [], "latest_timestamp": ""},
            )
            cluster["aliases"] = _dedupe_strings([*cluster["aliases"], entity])
            cluster["record_count"] = int(cluster.get("record_count") or 0) + 1
            cluster["event_types"] = _dedupe_strings([*cluster.get("event_types", []), event_type])
            cluster["latest_timestamp"] = max(str(cluster.get("latest_timestamp") or ""), timestamp)

            entity_node_id = f"entity:{normalized}"
            if entity_node_id not in node_seen:
                node_seen.add(entity_node_id)
                nodes.append({"id": entity_node_id, "kind": "entity", "label": entity})
            edge_marker = f"{entity_node_id}->{event_node_id}:mentions"
            if edge_marker not in edge_seen:
                edge_seen.add(edge_marker)
                edges.append({"source": entity_node_id, "target": event_node_id, "kind": "mentions"})

            for entry in card.get("state_history", []):
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("entity") or "").strip().lower() != normalized:
                    continue
                state_history[normalized].append(entry)

            if event_cards:
                event_chains[normalized].append(
                    {
                        "timestamp": timestamp,
                        "event_type": event_type,
                        "display_names": _card_field_values(event_cards, "display_name"),
                        "record_path": card.get("record_path"),
                    }
                )
            elif numeric_cards:
                event_chains[normalized].append(
                    {
                        "timestamp": timestamp,
                        "event_type": event_type,
                        "display_names": _card_field_values(numeric_cards, "value"),
                        "record_path": card.get("record_path"),
                    }
                )

        for relation in relations:
            subject = str(relation.get("subject") or "").strip()
            obj = str(relation.get("object") or "").strip()
            if not subject or not obj:
                continue
            source_id = f"entity:{subject.lower()}"
            target_id = f"entity:{obj.lower()}"
            if source_id not in node_seen:
                node_seen.add(source_id)
                nodes.append({"id": source_id, "kind": "entity", "label": subject})
            if target_id not in node_seen:
                node_seen.add(target_id)
                nodes.append({"id": target_id, "kind": "entity", "label": obj})
            edge_marker = f"{source_id}->{target_id}:{relation.get('kind') or 'relation'}"
            if edge_marker not in edge_seen:
                edge_seen.add(edge_marker)
                edges.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "kind": str(relation.get("kind") or "relation"),
                        "label": str(relation.get("value") or ""),
                    }
                )

    serialized_state_history: dict[str, list[dict[str, Any]]] = {}
    for entity, history in state_history.items():
        sorted_history = sorted(history, key=lambda item: str(item.get("timestamp") or ""))
        serialized_state_history[entity] = sorted_history[-12:]
        if sorted_history:
            current_state[entity] = sorted_history[-1]
        unique_attribute_values = {(str(item.get("attribute") or ""), str(item.get("value") or "")) for item in sorted_history}
        if len(unique_attribute_values) > 1:
            conflicts.append(
                {
                    "entity": entity,
                    "values": [
                        {"attribute": attribute, "value": value}
                        for attribute, value in sorted(unique_attribute_values)
                    ],
                    "resolution": "latest_wins",
                    "current_value": current_state[entity],
                }
            )

    reflection_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "entity_clusters": sorted(entity_clusters.values(), key=lambda item: (-int(item.get("record_count") or 0), item["canonical_entity"]))[:200],
        "event_chains": [
            {"entity": entity, "timeline": sorted(events, key=lambda item: str(item.get("timestamp") or ""))[-12:]}
            for entity, events in sorted(event_chains.items())
        ],
        "conflicts": conflicts[:120],
        "current_state": current_state,
        "state_history": serialized_state_history,
    }
    graph_payload = {
        "generated_at": reflection_payload["generated_at"],
        "nodes": nodes[:500],
        "edges": edges[:1000],
    }
    event_bus_payload = build_event_bus_snapshot(cards)

    reflection_path = system_dir / "reflection-latest.json"
    graph_path = system_dir / "memory-graph-latest.json"
    event_bus_path = system_dir / EVENT_BUS_FILE_NAME
    with reflection_path.open("w", encoding="utf-8") as file:
        json.dump(reflection_payload, file, ensure_ascii=False, indent=2)
    with graph_path.open("w", encoding="utf-8") as file:
        json.dump(graph_payload, file, ensure_ascii=False, indent=2)
    with event_bus_path.open("w", encoding="utf-8") as file:
        json.dump(event_bus_payload, file, ensure_ascii=False, indent=2)
    return {
        "reflection_path": str(reflection_path),
        "graph_path": str(graph_path),
        "event_bus_path": str(event_bus_path),
    }
