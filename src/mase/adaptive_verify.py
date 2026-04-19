"""Adaptive verification depth policy.

Pluggable, pure-decision module that routes retrieval results to one of three
verifier depths:

    - "skip"   : retrieval is high-confidence and dominant; no cloud verifier
    - "single" : medium confidence; current single-verifier chain (kimi-k2.5)
    - "dual"   : low confidence or hard qtype; dual-verifier vote for precision

The module performs no I/O. Default thresholds are tuned for LongMemEval and
overridable via env vars so an ablation can sweep without code changes.

Activation is gated by ``MASE_ADAPTIVE_VERIFY=1`` at the call site; this module
itself is always safe to import and call — when callers don't consult it, the
existing single-verifier chain runs unchanged (zero behavioral drift).
"""
from __future__ import annotations

import os
from typing import Literal

Decision = Literal["skip", "single", "dual"]

# Question types that empirically benefit from dual-verifier voting on LME
# (multi-session synthesis + temporal reasoning are the historic weak spots).
HARD_QTYPES: frozenset[str] = frozenset({"multi-session", "temporal-reasoning"})

DEFAULT_SKIP_THRESHOLD = 0.85
DEFAULT_DUAL_THRESHOLD = 0.5
DEFAULT_DOMINANCE_GAP = 0.2


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class AdaptiveVerifyPolicy:
    """Pure decision policy: retrieval signal -> verifier depth.

    Parameters
    ----------
    skip_threshold : float | None
        Minimum top-1 retrieval score required to consider skipping the
        verifier. Combined with ``dominance_gap``. Env override:
        ``MASE_VERIFY_SKIP_THRESHOLD``.
    dual_threshold : float | None
        Top-1 score below which the dual-verifier vote is engaged. Env
        override: ``MASE_VERIFY_DUAL_THRESHOLD``.
    dominance_gap : float | None
        Minimum (top1 - top2) gap required for "skip"; prevents skipping
        when several candidates are clustered near the top.
    """

    def __init__(
        self,
        skip_threshold: float | None = None,
        dual_threshold: float | None = None,
        dominance_gap: float | None = None,
    ) -> None:
        self.skip_threshold = (
            skip_threshold
            if skip_threshold is not None
            else _env_float("MASE_VERIFY_SKIP_THRESHOLD", DEFAULT_SKIP_THRESHOLD)
        )
        self.dual_threshold = (
            dual_threshold
            if dual_threshold is not None
            else _env_float("MASE_VERIFY_DUAL_THRESHOLD", DEFAULT_DUAL_THRESHOLD)
        )
        self.dominance_gap = (
            dominance_gap
            if dominance_gap is not None
            else _env_float("MASE_VERIFY_DOMINANCE_GAP", DEFAULT_DOMINANCE_GAP)
        )

    @staticmethod
    def _candidate_score(c: object) -> float | None:
        if isinstance(c, dict):
            for key in ("score", "similarity", "rerank_score", "confidence"):
                v = c.get(key)
                if isinstance(v, (int, float)):
                    return float(v)
        return None

    def _top_gap(self, candidates: list[dict]) -> float:
        if not candidates or len(candidates) < 2:
            return float("inf")  # only one candidate -> trivially dominant
        scores = [s for s in (self._candidate_score(c) for c in candidates) if s is not None]
        if len(scores) < 2:
            return float("inf")
        scores.sort(reverse=True)
        return scores[0] - scores[1]

    def decide(
        self,
        retrieval_score: float,
        candidates: list[dict],
        qtype: str | None = None,
    ) -> Decision:
        """Map (score, candidates, qtype) -> verifier depth.

        Hard qtypes always escalate to "dual" regardless of score — the
        precision win on multi-session/temporal questions outweighs the
        extra verifier call.
        """
        if qtype in HARD_QTYPES:
            return "dual"

        try:
            score = float(retrieval_score)
        except (TypeError, ValueError):
            return "single"

        if score < self.dual_threshold:
            return "dual"

        if score >= self.skip_threshold and self._top_gap(candidates) > self.dominance_gap:
            return "skip"

        return "single"


__all__ = ["AdaptiveVerifyPolicy", "Decision", "HARD_QTYPES"]
