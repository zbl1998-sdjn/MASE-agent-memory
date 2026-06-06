"""Markdown 审计日志写入工具。"""

# 注意：BASE_DIR 在 src/ 迁移时自动补丁为 parents[2]，确保仍解析到项目根。
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .model_interface import load_memory_settings

BASE_DIR = Path(__file__).resolve().parents[2]
_TRUTHY = {"1", "true", "yes", "y", "on"}


def _get_default_memory_dir() -> Path:
    """从配置中读取默认 memory 目录。"""
    return load_memory_settings().get("json_dir", BASE_DIR / "memory")


def _get_default_logs_dir() -> Path:
    """从配置中读取默认日志目录。"""
    return load_memory_settings().get("log_dir", BASE_DIR / "memory" / "logs")


def _get_logs_dir() -> Path:
    """解析当前写入日志目录，支持 MASE_MEMORY_DIR 覆盖 memory 根。"""
    override_dir = os.environ.get("MASE_MEMORY_DIR")
    if not override_dir:
        return _get_default_logs_dir()

    override_memory_dir = Path(override_dir).resolve()
    default_memory_dir = _get_default_memory_dir()
    default_logs_dir = _get_default_logs_dir()
    try:
        relative_logs_path = default_logs_dir.relative_to(default_memory_dir)
    except ValueError:
        # 配置中的 log_dir 不在 memory_dir 下时，覆盖目录统一落到 logs 子目录。
        relative_logs_path = Path("logs")
    return (override_memory_dir / relative_logs_path).resolve()


def _get_global_logs_dir() -> Path:
    return _get_default_logs_dir()


def ensure_logs_dir() -> Path:
    """确保当前日志目录存在。"""
    logs_dir = _get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def ensure_global_logs_dir() -> Path:
    """确保全局日志目录存在。"""
    global_logs_dir = _get_global_logs_dir()
    global_logs_dir.mkdir(parents=True, exist_ok=True)
    return global_logs_dir


def _global_log_mirroring_enabled() -> bool:
    """读取是否把覆盖日志同时镜像到默认全局日志目录。"""
    return os.environ.get("MASE_MIRROR_GLOBAL_LOGS", "").strip().lower() in _TRUTHY


def _normalize_markdown_text(value: Any) -> str:
    """把日志字段归一成 Markdown 友好的文本。"""
    text = str(value or "").strip()
    if not text:
        return "(空)"
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _build_markdown_entry(record: dict[str, Any]) -> str:
    """把一次交互记录渲染成单个 Markdown 段落。"""
    timestamp = str(record.get("timestamp", "")).strip()
    if "T" in timestamp:
        time_part = timestamp.split("T", 1)[1]
    else:
        time_part = datetime.now().strftime("%H:%M:%S")
    time_part = time_part.split(".", 1)[0]

    return (
        f"## 🕒 {time_part}\n\n"
        f"**用户**：{_normalize_markdown_text(record.get('user_query'))}\n\n"
        f"**助手**：{_normalize_markdown_text(record.get('assistant_response'))}\n\n"
        f"**摘要**：{_normalize_markdown_text(record.get('semantic_summary'))}\n\n"
        "---\n"
    )


def _append_entry(log_path: Path, date: str, entry: str) -> None:
    if not log_path.exists():
        header = f"# {date} 审计日志\n\n"
        log_path.write_text(header + entry, encoding="utf-8")
        return

    with log_path.open("a", encoding="utf-8") as file:
        if file.tell() > 0:
            file.write("\n")
        file.write(entry)


# 每日审计日志轮转上限，默认 5 MiB，可通过 MASE_AUDIT_MAX_BYTES 覆盖。
_DEFAULT_AUDIT_MAX_BYTES = 5 * 1024 * 1024


def _audit_max_bytes() -> int:
    """读取单个 Markdown 审计日志文件大小上限。"""
    raw = os.environ.get("MASE_AUDIT_MAX_BYTES", "").strip()
    if not raw:
        return _DEFAULT_AUDIT_MAX_BYTES
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_AUDIT_MAX_BYTES
    except ValueError:
        return _DEFAULT_AUDIT_MAX_BYTES


def _rotated_log_path(logs_dir: Path, date: str, entry_size: int) -> Path:
    """选择当天审计日志文件，满额时滚动到 `YYYY-MM-DD.001.md` 等。

    这样每个 Markdown 文件保持适合人工阅读（Notepad / Obsidian 友好）。
    """
    cap = _audit_max_bytes()
    base = logs_dir / f"{date}.md"
    if not base.exists() or base.stat().st_size + entry_size <= cap:
        return base
    idx = 1
    while True:
        candidate = logs_dir / f"{date}.{idx:03d}.md"
        if not candidate.exists() or candidate.stat().st_size + entry_size <= cap:
            return candidate
        idx += 1


def append_markdown_log(date: str, record: dict[str, Any]) -> str:
    """追加一条 Markdown 审计日志，并按配置可选镜像到全局日志目录。"""
    logs_dir = ensure_logs_dir()
    global_logs_dir = _get_global_logs_dir()
    mirror_global = global_logs_dir == logs_dir or _global_log_mirroring_enabled()
    if mirror_global:
        ensure_global_logs_dir()
    entry = _build_markdown_entry(record)
    entry_size = len(entry.encode("utf-8"))
    log_path = _rotated_log_path(logs_dir, date, entry_size)
    global_log_path = _rotated_log_path(global_logs_dir, date, entry_size)

    _append_entry(log_path, date, entry)
    if mirror_global and global_log_path != log_path:
        _append_entry(global_log_path, date, entry)

    return str(log_path)
