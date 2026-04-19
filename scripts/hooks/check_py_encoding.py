#!/usr/bin/env python3
"""Pre-commit hook: reject .py files that are UTF-16 encoded or contain NUL bytes.

Regression guard for the `mcp_tools.py` UTF-16-LE incident. CPython cannot compile
such files (`SyntaxError: source code string cannot contain null bytes`).
"""
from __future__ import annotations

import pathlib
import sys


def _is_bad(path: pathlib.Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError as err:
        return f"unreadable ({err})"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return "UTF-16 BOM detected"
    if b"\x00" in data:
        return "contains NUL byte"
    return None


def main(argv: list[str]) -> int:
    failures: list[str] = []
    for arg in argv:
        p = pathlib.Path(arg)
        if p.suffix != ".py" or not p.is_file():
            continue
        reason = _is_bad(p)
        if reason:
            failures.append(f"{arg}: {reason}")
    if failures:
        print("Encoding gate failed:", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        print(
            "\nFix: re-save as UTF-8 without BOM, e.g. in PowerShell:\n"
            "    $c = Get-Content -Raw <file>; "
            '[IO.File]::WriteAllText((Resolve-Path <file>), $c, (New-Object Text.UTF8Encoding($false)))',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
