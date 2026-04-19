"""Event bus — decoupled pub/sub for engine lifecycle events.

Why
---
Robustness, observability, and hot-swap features all want to react to the
same engine events (route decided, model call failed, executor finished,
fact_sheet built, ...).  Wiring each one into ``engine.MASESystem`` directly
is exactly the god-class anti-pattern.

The event bus lets any module subscribe to a topic and receive every event
published under that topic, without the engine knowing about the subscriber.

Design
------
* Topic names are dotted strings, e.g. ``mase.route.decided``,
  ``mase.executor.done``, ``mase.model.call.failed``.
* Subscribers can listen on an exact topic or a topic prefix.  A subscription
  on ``"mase"`` receives every event in the system; a subscription on
  ``"mase.model"`` receives only model-related events.
* Publish is **fire-and-forget**: subscriber exceptions are caught and
  swallowed (with the exception object exposed via :meth:`drain_errors`)
  so a buggy logger cannot crash the engine.
* Events carry an immutable payload mapping plus an auto-generated
  ``trace_id`` so downstream observers can correlate router → notetaker →
  executor for one user question.
* Synchronous delivery only.  The whole engine runs in one Python process and
  benchmarks need deterministic ordering; async fan-out is intentionally out
  of scope.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

EventHandler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any]
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)


@dataclass
class _Subscription:
    pattern: str  # exact topic OR prefix (matches if event.topic == pattern or starts with pattern + ".")
    handler: EventHandler

    def matches(self, topic: str) -> bool:
        if self.pattern == topic:
            return True
        return topic.startswith(self.pattern + ".")


class EventBus:
    """Process-wide pub/sub bus.  Thread-safe; synchronous delivery."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: list[_Subscription] = []
        self._errors: list[tuple[str, BaseException]] = []
        self._max_errors = 256

    # ---- subscription ----
    def subscribe(self, pattern: str, handler: EventHandler) -> Callable[[], None]:
        if not pattern or not callable(handler):
            raise ValueError("subscribe requires a non-empty pattern and a callable handler")
        sub = _Subscription(pattern=pattern, handler=handler)
        with self._lock:
            self._subs.append(sub)

        def _unsubscribe() -> None:
            with self._lock:
                try:
                    self._subs.remove(sub)
                except ValueError:
                    pass

        return _unsubscribe

    def unsubscribe_all(self, pattern: str | None = None) -> int:
        with self._lock:
            if pattern is None:
                removed = len(self._subs)
                self._subs.clear()
                return removed
            keep = [s for s in self._subs if s.pattern != pattern]
            removed = len(self._subs) - len(keep)
            self._subs = keep
            return removed

    # ---- publish ----
    def publish(self, topic: str, payload: dict[str, Any] | None = None, trace_id: str | None = None) -> Event:
        if not topic:
            raise ValueError("topic must be a non-empty string")
        event = Event(
            topic=topic,
            payload=dict(payload or {}),
            trace_id=trace_id or uuid.uuid4().hex,
        )
        with self._lock:
            handlers = [s.handler for s in self._subs if s.matches(topic)]
        for handler in handlers:
            try:
                handler(event)
            except BaseException as exc:  # noqa: BLE001 — never let observers crash the engine
                with self._lock:
                    self._errors.append((topic, exc))
                    if len(self._errors) > self._max_errors:
                        self._errors = self._errors[-self._max_errors :]
        return event

    # ---- diagnostics ----
    def subscribers(self) -> list[str]:
        with self._lock:
            return [s.pattern for s in self._subs]

    def drain_errors(self) -> list[tuple[str, BaseException]]:
        with self._lock:
            errors = list(self._errors)
            self._errors.clear()
            return errors


_BUS = EventBus()


def get_bus() -> EventBus:
    return _BUS


def publish(topic: str, payload: dict[str, Any] | None = None, trace_id: str | None = None) -> Event:
    return _BUS.publish(topic, payload, trace_id)


def subscribe(pattern: str, handler: EventHandler) -> Callable[[], None]:
    return _BUS.subscribe(pattern, handler)


# ---- canonical topic constants (so subscribers and engine agree on names) ----
class Topics:
    ROUTE_DECIDED = "mase.route.decided"
    NOTETAKER_SEARCH_DONE = "mase.notetaker.search.done"
    NOTETAKER_FACT_SHEET_DONE = "mase.notetaker.fact_sheet.done"
    EXECUTOR_CALL_START = "mase.executor.call.start"
    EXECUTOR_CALL_DONE = "mase.executor.call.done"
    EXECUTOR_VERIFY_DONE = "mase.executor.verify.done"
    RUN_DONE = "mase.run.done"
    MODEL_CALL_FAILED = "mase.model.call.failed"
    MODEL_FALLBACK_USED = "mase.model.fallback.used"


__all__ = [
    "Event",
    "EventBus",
    "EventHandler",
    "Topics",
    "get_bus",
    "publish",
    "subscribe",
]
