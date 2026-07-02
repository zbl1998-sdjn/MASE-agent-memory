"""`mase ingest` 批处理命令行入口。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ingest import ingest_folder
from .security import DEFAULT_MAX_BYTES


def _ensure_utf8_stdout() -> None:
    """Windows 控制台默认 cp1252 打不出中文;重配为 UTF-8 并容错替换。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="mase ingest",
        description="批量摄取本地文档/图像(png/jpg/webp/gif/pdf)为白盒记忆事实。",
    )
    parser.add_argument("folder", help="待摄取的本地文件夹(默认同时作为路径 jail 根)")
    parser.add_argument("--mode", default=None, help="vision agent 模式,如 minicpm 切换 minicpm-v4.5")
    parser.add_argument("--force", action="store_true", help="忽略幂等跳过,强制重新抽取")
    parser.add_argument("--allowed-root", default=None, help="路径 jail 根目录(默认= folder)")
    parser.add_argument("--max-mb", type=int, default=DEFAULT_MAX_BYTES // (1024 * 1024), help="单文件大小上限 MB")
    args = parser.parse_args(argv)

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"[error] 目录不存在: {folder}")
        return 2

    report = ingest_folder(
        folder,
        allowed_root=Path(args.allowed_root) if args.allowed_root else None,
        mode=args.mode,
        force=args.force,
        max_bytes=args.max_mb * 1024 * 1024,
    )
    print(
        f"[ingest] processed={len(report.processed)} skipped={len(report.skipped)} "
        f"errors={len(report.infra_errors)} extractions={report.extractions} facts={report.facts_written}"
    )
    for item in report.skipped:
        print(f"  [skip] {item['file']}: {item['reason']}")
    for item in report.infra_errors:
        print(f"  [error] {item['file']}: {item['error']}")
    return 1 if report.infra_errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
