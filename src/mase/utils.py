"""MASE 模块共享的纯 helper。

这里不引入 agent、SQL 或 LLM 客户端，只复用配置路径解析等叶子级能力，
因此可以被上层模块安全导入。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .model_interface import resolve_config_path, resolve_runs_dir


def memory_root(config_path: str | Path | None = None) -> Path:
    """解析磁盘记忆目录，并优先尊重 MASE_MEMORY_DIR 覆盖。"""
    raw_memory_dir = os.environ.get("MASE_MEMORY_DIR")
    if raw_memory_dir:
        root = Path(raw_memory_dir).resolve()
    elif (runs_dir := resolve_runs_dir()) is not None:
        root = runs_dir / "memory"
    else:
        root = resolve_config_path(config_path).parent / "memory"
    root.mkdir(parents=True, exist_ok=True)
    return root


def normalize_json_text(content: str) -> dict[str, Any] | None:
    """从可能带 Markdown fence 的模型响应中尽力提取 JSON 对象。"""
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
