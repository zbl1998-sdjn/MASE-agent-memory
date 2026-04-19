"""``python -m mase`` CLI.

Currently small (reload-config / health / describe-models / ask) — the goal
is just to give operators an out-of-band knob.  Everything bigger should
live in dedicated scripts under ``scripts/``.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import describe_models, mase_ask, reload_system
from .config_schema import validate_config_path
from .health_tracker import get_tracker
from .metrics import get_metrics
from .schema_migrations import migrate as migrate_db
from .utils import memory_root


def _cmd_reload_config(args: argparse.Namespace) -> int:
    parsed, messages = validate_config_path(args.config or "config.json", strict=False)
    if parsed is None:
        print("config validation failed:", file=sys.stderr)
        for m in messages:
            print(f"  - {m}", file=sys.stderr)
        return 2
    if messages:
        print("config validation warnings:", file=sys.stderr)
        for m in messages:
            print(f"  - {m}", file=sys.stderr)
    reload_system(args.config)
    print("reloaded MASE system from", args.config or "config.json")
    return 0


def _cmd_health(args: argparse.Namespace) -> int:
    snap = get_tracker().snapshot()
    print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    if args.format == "prometheus":
        sys.stdout.write(get_metrics().format_prometheus())
        return 0
    print(json.dumps(get_metrics().snapshot(), indent=2, ensure_ascii=False))
    return 0


def _cmd_migrate_db(args: argparse.Namespace) -> int:
    db_path = args.db or (memory_root(args.config) / "memory.sqlite")
    result = migrate_db(db_path)
    print(json.dumps({"db": str(db_path), **result}, indent=2))
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    print(json.dumps(describe_models(args.config), indent=2, ensure_ascii=False))
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    print(mase_ask(args.question, log=not args.no_log))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mase", description="MASE — Multi-Agent System Evolution")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_reload = sub.add_parser("reload-config", help="Validate and hot-reload config.json")
    p_reload.add_argument("--config", default=None, help="Path to config.json (default: project default)")
    p_reload.set_defaults(func=_cmd_reload_config)

    p_health = sub.add_parser("health", help="Print health-tracker snapshot")
    p_health.set_defaults(func=_cmd_health)

    p_metrics = sub.add_parser("metrics", help="Print metrics snapshot (json or prometheus)")
    p_metrics.add_argument("--format", choices=["json", "prometheus"], default="json")
    p_metrics.set_defaults(func=_cmd_metrics)

    p_migrate = sub.add_parser("migrate-db", help="Run pending SQLite schema migrations")
    p_migrate.add_argument("--db", default=None, help="Path to memory.sqlite (default: derived from config)")
    p_migrate.add_argument("--config", default=None)
    p_migrate.set_defaults(func=_cmd_migrate_db)

    p_describe = sub.add_parser("describe-models", help="Print resolved model bindings per agent")
    p_describe.add_argument("--config", default=None)
    p_describe.set_defaults(func=_cmd_describe)

    p_ask = sub.add_parser("ask", help="One-shot question through the full MASE pipeline")
    p_ask.add_argument("question")
    p_ask.add_argument("--no-log", action="store_true", help="Don't write the interaction to memory")
    p_ask.set_defaults(func=_cmd_ask)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
