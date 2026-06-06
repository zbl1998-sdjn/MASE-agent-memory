"""OpenAI 兼容集成层的共享运行时对象。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"

# 允许直接从源码树运行 `python -m integrations.openai_compat.server`，
# 不要求用户先执行 editable install。
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mase import MemoryService  # noqa: E402
from mase.model_interface import resolve_config_path  # noqa: E402

SERVER_CONFIG_PATH = resolve_config_path(os.environ.get("MASE_CONFIG_PATH") or ROOT / "config.json")
# MemoryService 是路由层共享门面；具体读写仍由服务内部执行 scope/审计逻辑。
memory_service = MemoryService()

__all__ = ["FRONTEND_DIST", "ROOT", "SERVER_CONFIG_PATH", "memory_service"]
