"""根目录兼容 shim，真实实现位于 ``mase.notetaker_agent``。

Notetaker 的工具调用、事实抽取和写入策略都在 `src/mase` 中；
这个文件只保证迁移前调用方不破。
"""
from __future__ import annotations

import sys as _sys

from mase import notetaker_agent as _impl

# 旧根路径和新包路径共享同一实现对象，避免 notetaker 状态被拆成两份。
_sys.modules[__name__] = _impl
