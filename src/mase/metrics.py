"""Metrics — in-process counters/histograms aggregated from event bus.

Why not Prometheus client?
--------------------------
A benchmark tool that runs locally and produces JSON reports does not
benefit from a 3rd-party HTTP exporter.  We expose the same data via:

* ``Metrics.snapshot()`` — JSON dict, easy to embed in benchmark reports
* ``mase metrics`` CLI subcommand — print snapshot
* ``Metrics.format_prometheus()`` — text-format Prometheus exposition that
  any external scrape can serve, if you want one.

Counters are derived from event topics so adding a new event topic auto-
creates a counter; no need to edit this module for every new event.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

from .event_bus import Event, get_bus
from .health_tracker import get_tracker


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latency_sum_ms: dict[str, float] = defaultdict(float)
        self._latency_count: dict[str, int] = defaultdict(int)
        self._unsubscribe: Any = None

    def install(self) -> None:
        with self._lock:
            if self._unsubscribe is not None:
                return
            self._unsubscribe = get_bus().subscribe("mase", self._on_event)

    def uninstall(self) -> None:
        with self._lock:
            if self._unsubscribe is not None:
                try:
                    self._unsubscribe()
                except Exception:
                    pass
                self._unsubscribe = None

    def _on_event(self, event: Event) -> None:
        topic = event.topic
        with self._lock:
            self._counters[topic] += 1
            latency = event.payload.get("latency_ms")
            if isinstance(latency, int | float) and latency > 0:
                self._latency_sum_ms[topic] += float(latency)
                self._latency_count[topic] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            latencies = {
                topic: round(self._latency_sum_ms[topic] / self._latency_count[topic], 2)
                for topic in self._latency_count
                if self._latency_count[topic] > 0
            }
        return {
            "event_counters": counters,
            "latency_ms_avg": latencies,
            "candidate_health": get_tracker().snapshot(),
        }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._latency_sum_ms.clear()
            self._latency_count.clear()

    def format_prometheus(self) -> str:
        snap = self.snapshot()
        lines: list[str] = []
        for topic, count in sorted(snap["event_counters"].items()):
            metric = "mase_events_total{topic=\"%s\"} %d" % (topic, count)
            lines.append(metric)
        for topic, avg in sorted(snap["latency_ms_avg"].items()):
            lines.append("mase_event_latency_ms_avg{topic=\"%s\"} %.2f" % (topic, avg))
        for h in snap["candidate_health"]:
            labels = "provider=\"%s\",model=\"%s\"" % (h["provider"], h["model"])
            lines.append("mase_candidate_success_rate{%s} %.4f" % (labels, h["success_rate"]))
            lines.append("mase_candidate_calls_total{%s} %d" % (labels, h["total_calls"]))
            lines.append("mase_candidate_failures_total{%s} %d" % (labels, h["total_failures"]))
        return "\n".join(lines) + "\n"


_METRICS = Metrics()
_METRICS.install()


def get_metrics() -> Metrics:
    return _METRICS


__all__ = ["Metrics", "get_metrics"]
