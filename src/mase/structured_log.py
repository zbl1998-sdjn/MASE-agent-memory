"""Structured logger — subscribes to the event bus, emits JSON lines.

Why not depend on ``structlog``?  The project already pins ``httpx``,
``ollama``, ``pydantic``, etc.  Adding another dep just to format dicts as
JSON is overkill.  Stdlib ``logging`` + a tiny JSON formatter does the job
and keeps the install footprint identical to V1.

What it does
------------
On import (or ``configure()``), one subscriber is installed on the bus
pattern ``"mase"`` — i.e. every engine event.  Each event becomes one JSON
line on the configured handler (stderr by default), shaped like::

    {"ts": 1700000000.123, "trace_id": "abc...", "topic": "mase.executor.call.done",
     "executor_mode": "grounded_long_context", "answer_chars": 213}

Operators can ``tail -f mase.log`` and feed it straight into any log
pipeline (Loki, Datadog, ELK).  trace_id correlates router → notetaker →
executor for one request — invaluable for debugging the 32% of LongMemEval
failures that are now pipeline-routing problems rather than model problems.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Any

from .event_bus import Event, get_bus

_LOCK = threading.Lock()
_INSTALLED: dict[str, Any] = {"unsubscribe": None, "logger": None}


def _format_event(event: Event) -> str:
    record: dict[str, Any] = {
        "ts": round(event.timestamp, 3),
        "trace_id": event.trace_id,
        "topic": event.topic,
    }
    for key, value in event.payload.items():
        # Keep payloads JSON-serializable; fall back to repr.
        try:
            json.dumps(value)
            record[key] = value
        except TypeError:
            record[key] = repr(value)
    return json.dumps(record, ensure_ascii=False)


def configure(
    *,
    stream: Any | None = None,
    level: int = logging.INFO,
    pattern: str = "mase",
    logger_name: str = "mase",
) -> logging.Logger:
    """(Re-)install the structured logger.

    Repeated calls replace the previous subscription so reload-config does
    not duplicate every event line.
    """
    with _LOCK:
        previous = _INSTALLED.get("unsubscribe")
        if callable(previous):
            try:
                previous()
            except Exception:
                pass

        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        # Don't double-add handlers if user already wired one.
        if not logger.handlers:
            handler = logging.StreamHandler(stream or sys.stderr)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            logger.propagate = False

        def _emit(event: Event) -> None:
            try:
                logger.info(_format_event(event))
            except Exception:
                pass

        unsubscribe = get_bus().subscribe(pattern, _emit)
        _INSTALLED["unsubscribe"] = unsubscribe
        _INSTALLED["logger"] = logger
        return logger


def get_logger(name: str = "mase") -> logging.Logger:
    return logging.getLogger(name)


__all__ = ["configure", "get_logger"]
