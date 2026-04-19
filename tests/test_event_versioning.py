from __future__ import annotations

import unittest

from event_bus import build_event_bus_snapshot, query_event_bus
from event_versioning import (
    build_event_version_views,
    filter_active_events,
    get_event_version_view,
    resolve_event_versions,
)


def _make_event(
    event_id: str,
    logical_event_id: str,
    timestamp: str,
    *,
    event_type: str = "price_quote",
    display_name: str = "Quote",
    source: str = "",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "logical_event_id": logical_event_id,
        "event_type": event_type,
        "display_name": display_name,
        "normalized_name": display_name.lower(),
        "timestamp": timestamp,
        "entities": ["quote"],
        "scope_hints": {"months": [], "weekdays": [], "locations": []},
        "source": source or display_name,
        "polarity": "positive",
        "attributes": {},
        "record_path": f"memory\\{event_id}.json",
        "thread_id": "thread-1",
        "thread_label": "pricing",
        "provenance": "test",
    }


class EventVersioningTests(unittest.TestCase):
    def test_resolve_event_versions_builds_successor_chain(self) -> None:
        events = [
            _make_event("quote-v1", "quote:pricing", "2024-05-01T09:00:00", display_name="Initial quote", source="Initial quote was $120"),
            _make_event("quote-v2", "quote:pricing", "2024-05-01T10:00:00", display_name="Corrected quote", source="Corrected quote was $100"),
            _make_event("quote-v3", "quote:pricing", "2024-05-01T11:00:00", display_name="Final quote", source="Final quote was $90"),
            _make_event("other-v1", "quote:shipping", "2024-05-01T08:30:00", display_name="Shipping quote", source="Shipping quote was $15"),
        ]

        resolved = resolve_event_versions(events)
        by_id = {str(event["event_id"]): event for event in resolved}

        self.assertEqual(by_id["quote-v1"]["status"], "deprecated")
        self.assertEqual(by_id["quote-v1"]["deprecated_by"], "quote-v2")
        self.assertEqual(by_id["quote-v2"]["status"], "deprecated")
        self.assertEqual(by_id["quote-v2"]["deprecated_by"], "quote-v3")
        self.assertEqual(by_id["quote-v3"]["status"], "active")
        self.assertEqual(by_id["quote-v3"]["deprecated_by"], "")
        self.assertEqual(by_id["other-v1"]["status"], "active")

    def test_build_event_version_views_returns_current_previous_and_history(self) -> None:
        events = [
            _make_event("quote-v1", "quote:pricing", "2024-05-01T09:00:00", display_name="Initial quote"),
            _make_event("quote-v2", "quote:pricing", "2024-05-01T10:00:00", display_name="Corrected quote"),
            _make_event("quote-v3", "quote:pricing", "2024-05-01T11:00:00", display_name="Final quote"),
        ]

        views = build_event_version_views(events)
        quote_view = views["quote:pricing"]
        direct_view = get_event_version_view(events, "quote:pricing")

        self.assertEqual(quote_view["current"]["event_id"], "quote-v3")
        self.assertEqual(quote_view["previous"]["event_id"], "quote-v2")
        self.assertEqual([event["event_id"] for event in quote_view["history"]], ["quote-v1", "quote-v2", "quote-v3"])
        self.assertEqual([event["event_id"] for event in quote_view["active"]], ["quote-v3"])
        self.assertEqual([event["event_id"] for event in quote_view["deprecated"]], ["quote-v1", "quote-v2"])
        self.assertEqual(direct_view["current"]["event_id"], "quote-v3")
        self.assertEqual([event["event_id"] for event in filter_active_events(quote_view["history"])], ["quote-v3"])

    def test_event_bus_snapshot_queries_default_to_active_but_can_include_history(self) -> None:
        snapshot = build_event_bus_snapshot(
            [
                {
                    "events": [
                        _make_event("quote-v1", "quote:pricing", "2024-05-01T09:00:00", display_name="Initial quote", source="Initial quote was $120"),
                        _make_event("quote-v2", "quote:pricing", "2024-05-01T10:00:00", display_name="Corrected quote", source="Corrected quote was $100"),
                        _make_event("quote-v3", "quote:pricing", "2024-05-01T11:00:00", display_name="Final quote", source="Final quote was $90"),
                    ]
                }
            ]
        )

        active_matches = query_event_bus(snapshot, event_types=["price_quote"], limit=10)
        full_matches = query_event_bus(snapshot, event_types=["price_quote"], active_only=False, limit=10)

        self.assertEqual(snapshot["active_event_count"], 1)
        self.assertEqual([event["event_id"] for event in active_matches], ["quote-v3"])
        self.assertEqual([event["event_id"] for event in full_matches], ["quote-v3", "quote-v2", "quote-v1"])
        self.assertEqual(full_matches[1]["deprecated_by"], "quote-v3")
        self.assertEqual(full_matches[2]["deprecated_by"], "quote-v2")


if __name__ == "__main__":
    unittest.main()
