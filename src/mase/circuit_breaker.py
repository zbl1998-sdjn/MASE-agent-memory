"""Circuit breaker — ``open`` state on top of the health tracker.

The health tracker already implements a cooldown after N consecutive
failures, which is logically a half-open circuit.  This module exposes the
same notion under the standard breaker vocabulary so callers (and metrics
labels) can talk about it explicitly.

States:

* ``closed``  — calls flow normally
* ``open``    — calls would fail-fast (we still let one through to detect
                recovery; that's the standard half-open trick)
* ``half_open`` — implicit; same condition as ``open`` past the cooldown
                  window.

Why not ``pybreaker``?  Same reason as the structured logger: the project
already contains a working cooldown.  Layering pybreaker on top adds a
process-global lock per (provider, model) and a second source of truth.
This wrapper is 50 lines and reuses tracker state directly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .health_tracker import CandidateHealthTracker, get_tracker


@dataclass
class BreakerState:
    provider: str
    model: str
    state: str  # "closed" | "open" | "half_open"
    consecutive_failures: int
    seconds_until_retry: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "seconds_until_retry": round(self.seconds_until_retry, 1),
        }


def state_for(provider: str, model: str, tracker: CandidateHealthTracker | None = None) -> BreakerState:
    tracker = tracker or get_tracker()
    snap = {(h["provider"], h["model"]): h for h in tracker.snapshot()}
    health = snap.get((provider, model))
    if health is None or health["consecutive_failures"] < tracker.cooldown_failures:
        return BreakerState(provider=provider, model=model, state="closed",
                            consecutive_failures=health["consecutive_failures"] if health else 0,
                            seconds_until_retry=0.0)
    elapsed = time.time() - tracker._healths[(provider, model)].last_failure_at  # noqa: SLF001
    seconds_until_retry = max(0.0, tracker.cooldown_seconds - elapsed)
    if seconds_until_retry > 0:
        return BreakerState(
            provider=provider,
            model=model,
            state="open",
            consecutive_failures=health["consecutive_failures"],
            seconds_until_retry=seconds_until_retry,
        )
    return BreakerState(
        provider=provider,
        model=model,
        state="half_open",
        consecutive_failures=health["consecutive_failures"],
        seconds_until_retry=0.0,
    )


def snapshot(tracker: CandidateHealthTracker | None = None) -> list[dict[str, Any]]:
    tracker = tracker or get_tracker()
    return [
        state_for(h["provider"], h["model"], tracker=tracker).to_dict()
        for h in tracker.snapshot()
    ]


__all__ = ["BreakerState", "snapshot", "state_for"]
