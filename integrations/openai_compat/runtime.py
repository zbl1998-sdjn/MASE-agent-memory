from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mase import MemoryService  # noqa: E402
from mase.model_interface import resolve_config_path  # noqa: E402

SERVER_CONFIG_PATH = resolve_config_path(os.environ.get("MASE_CONFIG_PATH") or ROOT / "config.json")
memory_service = MemoryService()

__all__ = ["FRONTEND_DIST", "ROOT", "SERVER_CONFIG_PATH", "memory_service"]
