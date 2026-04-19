# NOTE: BASE_DIR below was auto-patched during src/ migration so that
# Path(__file__).parents[2] continues to resolve to the project root.
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .model_interface import load_memory_settings

BASE_DIR = Path(__file__).resolve().parents[2]


def _get_default_memory_dir() -> Path:
    return load_memory_settings().get("json_dir", BASE_DIR / "memory")


def _get_default_logs_dir() -> Path:
    return load_memory_settings().get("log_dir", BASE_DIR / "memory" / "logs")


def _get_logs_dir() -> Path:
    override_dir = os.environ.get("MASE_MEMORY_DIR")
    if not override_dir:
        return _get_default_logs_dir()

    override_memory_dir = Path(override_dir).resolve()
    default_memory_dir = _get_default_memory_dir()
    default_logs_dir = _get_default_logs_dir()
    try:
        relative_logs_path = default_logs_dir.relative_to(default_memory_dir)
    except ValueError:
        relative_logs_path = Path("logs")
    return (override_memory_dir / relative_logs_path).resolve()


def _get_global_logs_dir() -> Path:
    return _get_default_logs_dir()


def ensure_logs_dir() -> Path:
    logs_dir = _get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def ensure_global_logs_dir() -> Path:
    global_logs_dir = _get_global_logs_dir()
    global_logs_dir.mkdir(parents=True, exist_ok=True)
    return global_logs_dir


def _normalize_markdown_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "(空)"
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _build_markdown_entry(record: dict[str, Any]) -> str:
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


# Per-day audit-log rotation cap. Default 5 MiB. Override via MASE_AUDIT_MAX_BYTES.
_DEFAULT_AUDIT_MAX_BYTES = 5 * 1024 * 1024


def _audit_max_bytes() -> int:
    raw = os.environ.get("MASE_AUDIT_MAX_BYTES", "").strip()
    if not raw:
        return _DEFAULT_AUDIT_MAX_BYTES
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_AUDIT_MAX_BYTES
    except ValueError:
        return _DEFAULT_AUDIT_MAX_BYTES


def _rotated_log_path(logs_dir: Path, date: str, entry_size: int) -> Path:
    """Pick today's audit log file, rolling to `YYYY-MM-DD.001.md` etc when full.

    Keeps each markdown file readable for humans (Notepad / Obsidian friendly).
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
    logs_dir = ensure_logs_dir()
    ensure_global_logs_dir()
    entry = _build_markdown_entry(record)
    entry_size = len(entry.encode("utf-8"))
    log_path = _rotated_log_path(logs_dir, date, entry_size)
    global_log_path = _rotated_log_path(_get_global_logs_dir(), date, entry_size)

    _append_entry(log_path, date, entry)
    if global_log_path != log_path:
        _append_entry(global_log_path, date, entry)

    return str(log_path)
