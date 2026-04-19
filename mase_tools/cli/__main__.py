"""``python -m mase_tools.cli`` entry point.

Currently exposes a single subcommand group:

    python -m mase_tools.cli memory diff [--from REF] [--to REF] [--vault PATH]
"""
from __future__ import annotations

import argparse
import sys

from .memory_diff import add_memory_diff_args, run_memory_diff


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mase_tools.cli",
        description="MASE tri-vault inspection CLI.",
    )
    sub = parser.add_subparsers(dest="group", required=True)

    memory = sub.add_parser("memory", help="Memory vault commands.")
    memory_sub = memory.add_subparsers(dest="command", required=True)

    diff = memory_sub.add_parser(
        "diff",
        help="Show git-diff-style changes between tri-vault snapshots.",
    )
    add_memory_diff_args(diff)
    diff.set_defaults(func=run_memory_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
