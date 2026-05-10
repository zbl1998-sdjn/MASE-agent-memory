#!/usr/bin/env python3
"""Report local-only artifacts that make the repository hard to inspect.

The default mode is advisory and exits 0. CI uses ``--strict`` on a clean
checkout to prevent heavyweight runtime outputs from becoming part of the
project working tree.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path


LOCAL_ONLY_DIRS = (
    ".claude",
    ".worktrees",
    "benchmarks/external-benchmarks/BAMBOO/__pycache__",
    "benchmarks/external-benchmarks/BAMBOO/outputs",
    "benchmarks/external-benchmarks/NoLiMa/__pycache__",
    "benchmarks/external-benchmarks/NoLiMa/outputs",
    "data",
    "memory",
    "memory_runs",
    "proposals",
    "results",
    "run_artifacts",
)
LOCAL_ONLY_FILES = (
    "benchmarks/external-benchmarks/BAMBOO.zip",
    "benchmarks/external-benchmarks/NoLiMa.zip",
    "config.lme_cloud_swap.json",
    "event-bus-latest.json",
)
LOCAL_ONLY_GLOBS = (
    "_*.log",
    "scripts/_*.err",
    "scripts/_*.json",
    "scripts/_*.log",
    "scripts/_*.ps1",
    "scripts/_*.txt",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def find_local_artifacts(root: Path) -> list[str]:
    findings: list[str] = []
    for rel in (*LOCAL_ONLY_DIRS, *LOCAL_ONLY_FILES):
        path = root / rel
        if path.exists():
            findings.append(rel)
    for pattern in LOCAL_ONLY_GLOBS:
        findings.extend(_relative(path, root) for path in sorted(root.glob(pattern)) if path.exists())
    return sorted(dict.fromkeys(findings))


def _iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        return
    for child in path.rglob("*"):
        if child.is_file():
            yield child


def summarize_sizes(root: Path, findings: Iterable[str]) -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    for rel in findings:
        path = root / rel
        file_count = 0
        size_bytes = 0
        for item in _iter_files(path):
            file_count += 1
            try:
                size_bytes += item.stat().st_size
            except OSError:
                continue
        rows.append((rel, file_count, size_bytes))
    return rows


def render_report(findings: list[str], root: Path, include_sizes: bool = False) -> str:
    if not findings:
        return "Repo hygiene: no local-only artifact paths found."

    lines = [
        "Repo hygiene: local-only artifact paths are present.",
        "These paths are ignored, but keeping large outputs inside the repo slows git, IDE indexing, and code search.",
        "Preferred location for heavy runs: a sibling directory such as E:/MASE-runs.",
        "Set MASE_RUNS_DIR=E:/MASE-runs before new benchmark runs to keep outputs there by default.",
        "",
    ]
    if include_sizes:
        for rel, file_count, size_bytes in summarize_sizes(root, findings):
            lines.append(f"  - {rel} ({file_count} files, {size_bytes / 1024 / 1024:.2f} MB)")
    else:
        lines.extend(f"  - {rel}" for rel in findings)
        lines.append("")
        lines.append("Use --sizes for a recursive size report; it can be slow on large benchmark output trees.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=project_root(), help="Project root to inspect.")
    parser.add_argument("--sizes", action="store_true", help="Recursively compute file counts and sizes.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when local-only artifact paths exist.")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    findings = find_local_artifacts(root)
    print(render_report(findings, root, include_sizes=args.sizes))
    return 1 if args.strict and findings else 0


if __name__ == "__main__":
    sys.exit(main())
