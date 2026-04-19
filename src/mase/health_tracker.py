"""Candidate health tracker — health/cost/latency aware fallback ordering.

Why
---
``model_interface._iter_model_candidates`` currently returns the configured
candidates in a fixed order.  When DeepSeek goes down we waste seconds
trying it first every single time.  A simple in-process tracker can:

* learn which candidates are healthy right now
* give them priority on the next call
* put a candidate into cooldown after N consecutive failures so we don't
  hammer a dead endpoint
* break ties by latency and (optional) cost-per-1k-tokens
* always keep at least one local fallback as a last resort

The tracker is a process-singleton, thread-safe, and **never crashes the
caller**: every operation is best-effort.

It hooks into :mod:`event_bus` so observers (metrics, structured log) can
see the same outcomes the tracker sees.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .event_bus import get_bus

# How aggressively recent samples dominate older ones.  0 < alpha < 1; bigger
# alpha = react faster to fresh outcomes.  0.3 is a balance between "stable"
# and "responsive": one bad call drops a perfect-history candidate from
# 1.000 to 0.700 success rate, enough to demote it but not enough to send
# it to cooldown.
_EWMA_ALPHA = 0.3
_DEFAULT_COOLDOWN_FAILURES = 3
_DEFAULT_COOLDOWN_SECONDS = 30.0
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "llama_cpp", "llamacpp", "local"})


@dataclass
class CandidateHealth:
    provider: str
    model: str
    success_rate: float = 1.0
    latency_ms_ewma: float = 0.0
    consecutive_failures: int = 0
    last_failure_at: float = 0.0
    last_success_at: float = 0.0
    total_calls: int = 0
    total_failures: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.model)

    def is_in_cooldown(self, now: float, cooldown_failures: int, cooldown_seconds: float) -> bool:
        if self.consecutive_failures < cooldown_failures:
            return False
        return (now - self.last_failure_at) < cooldown_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "success_rate": round(self.success_rate, 4),
            "latency_ms_ewma": round(self.latency_ms_ewma, 1),
            "consecutive_failures": self.consecutive_failures,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
        }


class CandidateHealthTracker:
    def __init__(
        self,
        cooldown_failures: int = _DEFAULT_COOLDOWN_FAILURES,
        cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self.cooldown_failures = cooldown_failures
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.RLock()
        self._healths: dict[tuple[str, str], CandidateHealth] = {}

    # ---- recording ----
    def _get(self, provider: str, model: str) -> CandidateHealth:
        key = (provider, model)
        health = self._healths.get(key)
        if health is None:
            health = CandidateHealth(provider=provider, model=model)
            self._healths[key] = health
        return health

    def record_success(self, provider: str, model: str, latency_ms: float = 0.0) -> None:
        with self._lock:
            health = self._get(provider, model)
            health.total_calls += 1
            health.success_rate = (1 - _EWMA_ALPHA) * health.success_rate + _EWMA_ALPHA * 1.0
            if latency_ms > 0:
                if health.latency_ms_ewma == 0:
                    health.latency_ms_ewma = latency_ms
                else:
                    health.latency_ms_ewma = (1 - _EWMA_ALPHA) * health.latency_ms_ewma + _EWMA_ALPHA * latency_ms
            health.consecutive_failures = 0
            health.last_success_at = time.time()
        get_bus().publish("mase.health.success", {"provider": provider, "model": model, "latency_ms": latency_ms})

    def record_failure(self, provider: str, model: str, error: str = "") -> None:
        with self._lock:
            health = self._get(provider, model)
            health.total_calls += 1
            health.total_failures += 1
            health.success_rate = (1 - _EWMA_ALPHA) * health.success_rate + _EWMA_ALPHA * 0.0
            health.consecutive_failures += 1
            health.last_failure_at = time.time()
            in_cooldown = health.is_in_cooldown(health.last_failure_at, self.cooldown_failures, self.cooldown_seconds)
        get_bus().publish(
            "mase.health.failure",
            {"provider": provider, "model": model, "error": error[:240], "in_cooldown": in_cooldown},
        )

    # ---- ordering ----
    def score(self, provider: str, model: str, cost_per_1k: float = 0.0) -> float:
        """Higher is better.  Used for sort key (descending)."""
        with self._lock:
            health = self._healths.get((provider, model))
        if health is None:
            return 1.0  # unseen candidate: neutral-positive
        # success rate dominates; subtract a small penalty for slow latency
        # and cost.  Latency penalty caps at ~0.2 (slow but working still
        # beats fast-but-failing).
        latency_penalty = min(0.2, health.latency_ms_ewma / 60_000.0)
        cost_penalty = min(0.1, cost_per_1k / 50.0) if cost_per_1k > 0 else 0.0
        return health.success_rate - latency_penalty - cost_penalty

    def sort_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        prefer_local: bool = False,
    ) -> list[dict[str, Any]]:
        """Re-order candidates by health score; preserves first-pos preference for ties.

        Rules:
        1. Drop nothing — all candidates remain reachable.
        2. Skip-rank cooled-down candidates to the back (still reachable as
           a last resort if everything else fails).
        3. If ``prefer_local``, push provider in :data:`_LOCAL_PROVIDERS`
           to the very back UNLESS it's the only healthy option (handled by
           the calling layer's local-fallback append).
        """
        now = time.time()
        with self._lock:
            scored: list[tuple[float, int, dict[str, Any]]] = []
            for index, candidate in enumerate(candidates):
                provider = str(candidate.get("provider") or "")
                model = str(candidate.get("model_name") or "")
                cost = float(candidate.get("cost_per_1k_tokens") or 0.0)
                base = self.score(provider, model, cost_per_1k=cost)
                health = self._healths.get((provider, model))
                cooldown_penalty = 0.0
                if health is not None and health.is_in_cooldown(now, self.cooldown_failures, self.cooldown_seconds):
                    cooldown_penalty = 1.0
                scored.append((base - cooldown_penalty, index, candidate))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [item[2] for item in scored]

    # ---- inspection ----
    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [h.to_dict() for h in self._healths.values()]

    def reset(self) -> None:
        with self._lock:
            self._healths.clear()


_TRACKER = CandidateHealthTracker()


def get_tracker() -> CandidateHealthTracker:
    return _TRACKER


def is_local_provider(provider: str) -> bool:
    return str(provider or "").lower() in _LOCAL_PROVIDERS


__all__ = [
    "CandidateHealth",
    "CandidateHealthTracker",
    "get_tracker",
    "is_local_provider",
]
