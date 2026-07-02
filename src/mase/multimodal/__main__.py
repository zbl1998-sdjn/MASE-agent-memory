"""`python -m mase.multimodal ingest <folder>` 入口。"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "ingest":
        argv = argv[1:]
    raise SystemExit(main(argv))
