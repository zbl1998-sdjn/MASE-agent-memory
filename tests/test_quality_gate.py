from __future__ import annotations

import pytest

from scripts import quality_gate
from scripts.quality_gate import GateStep, build_steps, main

_QUICK_STEP_NAMES = [
    "ruff-lint",
    "mypy-types",
    "arch-imports",
    "api-docstrings",
    "anti-overfit",
    "governance-eval",
    "pytest-fast",
]
_FRONTEND_STEP_NAMES = ["frontend-typecheck", "frontend-test", "frontend-build"]


def test_quick_level_covers_python_gates_in_layer_order() -> None:
    names = [step.name for step in build_steps("quick", governance_out_dir="X")]
    assert names == _QUICK_STEP_NAMES


def test_full_level_appends_frontend_gates() -> None:
    names = [step.name for step in build_steps("full", governance_out_dir="X")]
    assert names == _QUICK_STEP_NAMES + _FRONTEND_STEP_NAMES


def test_governance_eval_step_uses_injected_out_dir() -> None:
    steps = {s.name: s for s in build_steps("quick", governance_out_dir="E:/some/dir")}
    assert steps["governance-eval"].command[-1] == "E:/some/dir"


def test_list_mode_prints_without_running(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(step: GateStep) -> tuple[bool, float, str]:
        raise AssertionError(f"--list must not execute steps, ran {step.name}")

    monkeypatch.setattr(quality_gate, "run_step", _boom)
    assert main(["--level", "full", "--list"]) == 0
    out = capsys.readouterr().out
    for name in _QUICK_STEP_NAMES + _FRONTEND_STEP_NAMES:
        assert name in out


def test_fail_fast_stops_at_first_red_step(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    executed: list[str] = []

    def _fake_run(step: GateStep) -> tuple[bool, float, str]:
        executed.append(step.name)
        return (step.name != "mypy-types", 0.01, f"tail of {step.name}")

    monkeypatch.setattr(quality_gate, "run_step", _fake_run)
    assert main(["--level", "quick"]) == 1
    assert executed == ["ruff-lint", "mypy-types"]
    out = capsys.readouterr().out
    assert "QUALITY_GATE_RESULT=failed level=quick step=mypy-types" in out


def test_all_green_reports_passed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(quality_gate, "run_step", lambda step: (True, 0.01, ""))
    assert main(["--level", "quick"]) == 0
    assert "QUALITY_GATE_RESULT=passed level=quick steps=7" in capsys.readouterr().out
