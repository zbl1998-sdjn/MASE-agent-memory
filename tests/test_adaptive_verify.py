"""Unit tests for the adaptive verification policy.

Covers the four canonical paths:
  1. high score + dominant top-1     -> "skip"
  2. mid-range score                  -> "single"
  3. multi-session qtype              -> "dual"
  4. default OFF (no env flag)        -> hook is inert -> "single"
"""
from __future__ import annotations

import pytest

from mase.adaptive_verify import AdaptiveVerifyPolicy
from mase.router import adaptive_verify_decision


def _cands(*scores: float) -> list[dict]:
    return [{"id": f"c{i}", "score": s} for i, s in enumerate(scores)]


def test_high_score_dominant_skips_verifier() -> None:
    policy = AdaptiveVerifyPolicy()
    decision = policy.decide(0.92, _cands(0.92, 0.55), qtype="single-session-user")
    assert decision == "skip"


def test_mid_score_uses_single_verifier() -> None:
    policy = AdaptiveVerifyPolicy()
    decision = policy.decide(0.70, _cands(0.70, 0.65), qtype="single-session-user")
    assert decision == "single"


def test_multi_session_forces_dual_vote() -> None:
    policy = AdaptiveVerifyPolicy()
    decision = policy.decide(0.95, _cands(0.95, 0.30), qtype="multi-session")
    assert decision == "dual"


def test_default_off_router_hook_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MASE_ADAPTIVE_VERIFY", raising=False)
    result = adaptive_verify_decision(0.99, _cands(0.99, 0.10), qtype="multi-session")
    assert result == "single"


def test_flag_on_router_hook_consults_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_ADAPTIVE_VERIFY", "1")
    assert adaptive_verify_decision(0.99, _cands(0.99, 0.10)) == "skip"
    assert adaptive_verify_decision(0.30, _cands(0.30, 0.20)) == "dual"
    assert adaptive_verify_decision(0.70, _cands(0.70, 0.65)) == "single"


def test_high_score_but_clustered_does_not_skip() -> None:
    policy = AdaptiveVerifyPolicy()
    # gap (0.86 - 0.84 = 0.02) is below default dominance threshold
    decision = policy.decide(0.86, _cands(0.86, 0.84))
    assert decision == "single"


def test_env_threshold_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_VERIFY_SKIP_THRESHOLD", "0.95")
    monkeypatch.setenv("MASE_VERIFY_DUAL_THRESHOLD", "0.6")
    policy = AdaptiveVerifyPolicy()
    # 0.90 used to skip; with threshold raised to 0.95 it should now be single
    assert policy.decide(0.90, _cands(0.90, 0.40)) == "single"
    # 0.55 used to be single; with dual threshold raised to 0.6 -> dual
    assert policy.decide(0.55, _cands(0.55, 0.20)) == "dual"
