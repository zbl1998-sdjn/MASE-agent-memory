#!/usr/bin/env python3
"""MASE 项目质量闸:聚合仓库既有真实门禁,供人工验收与全局 Stop hook 调用。

用法:
    python -X utf8 scripts/quality_gate.py --level quick   # 收尾自检(纯 Python 侧,分钟内)
    python -X utf8 scripts/quality_gate.py --level full    # 生产验收口径(含前端三闸)
    python -X utf8 scripts/quality_gate.py --level full --list   # 只列步骤不执行

与 ``~/.agents/quality-gate/global_quality_gate.py`` 分发器的契约:退出码 0 = 全绿,
非 0 = 有失败;失败即 fail-fast(先修最低失败层)。步骤全部复用 CI 与 CHANGELOG
验证清单里的既有检查,不发明新口径。``audit_repo_hygiene --strict`` 是 CI 清树
专用(本地树的 .claude/memory 等会误红),故不入本地闸,由 CI 把守。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_TAIL_CHARS = 4000


@dataclass(frozen=True)
class GateStep:
    """一道门禁:名称 + 完整命令;命令在仓库根目录执行。"""

    name: str
    command: tuple[str, ...]


def _py(*args: str) -> tuple[str, ...]:
    return (sys.executable, "-X", "utf8", *args)


def _npm(*args: str) -> tuple[str, ...]:
    npm = shutil.which("npm") or "npm"
    return (npm, "--prefix", "frontend", *args)


def build_steps(level: str, governance_out_dir: str | None = None) -> list[GateStep]:
    """按级别构建步骤表;静态检查在前、测试在后(先修最低失败层)。"""
    gov_out = governance_out_dir or tempfile.mkdtemp(prefix="mase-quality-gate-gov-")
    quick = [
        GateStep("ruff-lint", _py("-m", "ruff", "check", ".")),
        GateStep("mypy-types", _py("-m", "mypy")),
        GateStep("arch-imports", _py("scripts/audit_architecture_imports.py", "--strict")),
        GateStep("api-docstrings", _py("scripts/audit_public_api_docstrings.py", "--strict")),
        GateStep("anti-overfit", _py("scripts/audit_anti_overfit.py", "--strict")),
        GateStep("governance-eval", _py("scripts/run_governance_eval.py", "--out-dir", gov_out)),
        GateStep("pytest-fast", _py("-m", "pytest", "-m", "not integration and not slow", "-q")),
    ]
    if level == "quick":
        return quick
    return [
        *quick,
        GateStep("frontend-typecheck", _npm("run", "typecheck")),
        GateStep("frontend-test", _npm("test")),
        GateStep("frontend-build", _npm("run", "build")),
    ]


def run_step(step: GateStep) -> tuple[bool, float, str]:
    """执行一道门禁,返回 (是否通过, 耗时秒, 输出尾部)。"""
    started = time.time()
    try:
        completed = subprocess.run(
            list(step.command),
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:  # 命令本身不可用(如未装 npm)也是失败,不是跳过
        return False, time.time() - started, f"command not runnable: {exc}"
    tail = (completed.stdout or "")[-_TAIL_CHARS:] + (completed.stderr or "")[-_TAIL_CHARS:]
    return completed.returncode == 0, time.time() - started, tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MASE repo quality gate.")
    parser.add_argument("--level", choices=["quick", "full"], default="quick")
    parser.add_argument("--list", action="store_true", help="print steps without running")
    args = parser.parse_args(argv)

    steps = build_steps(args.level)
    if args.list:
        for step in steps:
            print(f"{step.name}: {' '.join(step.command)}")
        return 0

    total_started = time.time()
    for step in steps:
        ok, duration, tail = run_step(step)
        status = "PASS" if ok else "FAIL"
        print(f"[gate] {step.name} ... {status} ({duration:.1f}s)", flush=True)
        if not ok:
            print(tail)
            print(f"QUALITY_GATE_RESULT=failed level={args.level} step={step.name}")
            return 1
    total = time.time() - total_started
    print(f"QUALITY_GATE_RESULT=passed level={args.level} steps={len(steps)} duration={total:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
