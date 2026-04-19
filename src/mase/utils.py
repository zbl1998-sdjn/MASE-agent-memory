"""Pure helper utilities shared across MASE modules.

Anything in here MUST be free of dependencies on agents, model interfaces or
SQL — they are leaf-level helpers safe to import from anywhere.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .model_interface import resolve_config_path


def memory_root(config_path: str | Path | None = None) -> Path:
    """Resolve the on-disk memory directory honoring MASE_MEMORY_DIR override."""
    raw_memory_dir = os.environ.get("MASE_MEMORY_DIR")
    if raw_memory_dir:
        root = Path(raw_memory_dir).resolve()
    else:
        root = resolve_config_path(config_path).parent / "memory"
    root.mkdir(parents=True, exist_ok=True)
    return root


def normalize_json_text(content: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction from a possibly fenced model response."""
    cleaned = str(content or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
