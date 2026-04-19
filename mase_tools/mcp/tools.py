"""Real MCP tool implementations for MASE.

Replaces the V1 mock layer (``return f"Content of {filepath} (simulated)"``)
with sandboxed, size-capped, encoding-tolerant disk access plus a directory
listing helper. Sandbox is opt-in via the ``MASE_MCP_SANDBOX`` env var; in its
absence ``read_local_file`` refuses to touch the filesystem so an LLM cannot
exfiltrate arbitrary host files just by emitting a filepath argument.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

# Configuration knobs (tunable via env so deployments don't have to fork code).
MAX_READ_BYTES = int(os.environ.get("MASE_MCP_MAX_READ_BYTES", str(256 * 1024)))  # 256 KiB
SANDBOX_ENV = "MASE_MCP_SANDBOX"


def _resolve_sandbox() -> Path | None:
    raw = os.environ.get(SANDBOX_ENV)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _within_sandbox(target: Path, sandbox: Path) -> bool:
    try:
        target.relative_to(sandbox)
        return True
    except ValueError:
        return False


def get_current_time() -> str:
    """Returns the current system time (ISO-ish, second precision)."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_local_file(filepath: str) -> str:
    """Read a UTF-8 text file from the configured MCP sandbox.

    Refuses to read when no sandbox is configured (``MASE_MCP_SANDBOX``).
    Returns a clearly-tagged error string instead of raising — the caller is an
    LLM tool-use loop and benefits from a consumable explanation rather than a
    stack trace.
    """
    sandbox = _resolve_sandbox()
    if sandbox is None:
        return (
            "[mcp:read_local_file:error] disabled — set MASE_MCP_SANDBOX to a "
            "directory path to enable file reads"
        )
    try:
        target = (sandbox / filepath).resolve() if not Path(filepath).is_absolute() else Path(filepath).resolve()
    except OSError as exc:
        return f"[mcp:read_local_file:error] invalid path: {exc}"
    if not _within_sandbox(target, sandbox):
        return f"[mcp:read_local_file:error] path escapes sandbox: {target}"
    if not target.exists():
        return f"[mcp:read_local_file:error] not found: {target}"
    if not target.is_file():
        return f"[mcp:read_local_file:error] not a regular file: {target}"
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        return (
            f"[mcp:read_local_file:error] file too large ({size} bytes > "
            f"{MAX_READ_BYTES} cap)"
        )
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return target.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return "[mcp:read_local_file:error] could not decode file as text"


def list_directory(dirpath: str = ".") -> str:
    """List a directory inside the sandbox (one entry per line, dirs end in '/')."""
    sandbox = _resolve_sandbox()
    if sandbox is None:
        return (
            "[mcp:list_directory:error] disabled — set MASE_MCP_SANDBOX to a "
            "directory path to enable listings"
        )
    try:
        target = (sandbox / dirpath).resolve() if not Path(dirpath).is_absolute() else Path(dirpath).resolve()
    except OSError as exc:
        return f"[mcp:list_directory:error] invalid path: {exc}"
    if not _within_sandbox(target, sandbox):
        return f"[mcp:list_directory:error] path escapes sandbox: {target}"
    if not target.is_dir():
        return f"[mcp:list_directory:error] not a directory: {target}"
    entries = []
    for child in sorted(target.iterdir()):
        entries.append(child.name + ("/" if child.is_dir() else ""))
    return "\n".join(entries) if entries else "[mcp:list_directory] empty"


# A simple registry of available tools (kept stable for the executor's tool-use loop).
TOOL_REGISTRY = {
    "get_current_time": get_current_time,
    "read_local_file": read_local_file,
    "list_directory": list_directory,
}