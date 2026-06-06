"""根目录兼容 shim，真实实现位于 ``mase.notetaker``。

Markdown 审计日志与 tri-vault 写入逻辑不在根目录维护；
新实现请看 `src/mase/notetaker.py`。
"""
from __future__ import annotations

import sys as _sys

from mase import notetaker as _impl

# 兼容导入只做模块别名，不复制实现。
_sys.modules[__name__] = _impl
