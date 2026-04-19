from __future__ import annotations

import argparse
import types
import sys

sys.modules.setdefault("ipdb", types.SimpleNamespace(set_trace=lambda *args, **kwargs: None))
sys.modules.setdefault("autopep8", types.SimpleNamespace(fix_code=lambda code, options=None: code))
sys.modules.setdefault("docformatter", types.SimpleNamespace(format_code=lambda code, **kwargs: code))

import evaluate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run official BAMBOO evaluate.py with local dependency shims.")
    parser.add_argument("--input_path", required=True)
    parser.add_argument("--task", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evaluate.evaluate(args.input_path, args.task)


if __name__ == "__main__":
    main()
