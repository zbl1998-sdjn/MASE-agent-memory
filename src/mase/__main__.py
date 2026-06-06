"""``python -m mase`` 命令行入口。

当前只保留小型运维命令（reload-config / health / describe-models / ask），用于给
操作者一个旁路控制面。更复杂的批处理应放到 ``scripts/`` 下的专用脚本。
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
    """校验并热重载配置。"""
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
    """输出候选模型健康快照。"""
    snap = get_tracker().snapshot()
    print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    """输出指标快照，支持 JSON 和 Prometheus 文本格式。"""
    if args.format == "prometheus":
        sys.stdout.write(get_metrics().format_prometheus())
        return 0
    print(json.dumps(get_metrics().snapshot(), indent=2, ensure_ascii=False))
    return 0


def _cmd_migrate_db(args: argparse.Namespace) -> int:
    """执行 SQLite schema migration。"""
    db_path = args.db or (memory_root(args.config) / "memory.sqlite")
    result = migrate_db(db_path)
    print(json.dumps({"db": str(db_path), **result}, indent=2))
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    """输出每个 agent 解析后的模型绑定。"""
    print(json.dumps(describe_models(args.config), indent=2, ensure_ascii=False))
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    """通过完整 MASE pipeline 执行一次问答。"""
    print(mase_ask(args.question, log=not args.no_log))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """构造顶层 argparse parser。"""
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
    """CLI 主入口，返回进程退出码。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
