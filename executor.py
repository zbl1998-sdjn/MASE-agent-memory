"""根目录兼容 shim，真实实现位于 ``mase.executor``。

保留它只是为了让旧脚本里的 ``from executor import X`` 继续可用。
新代码应直接从 ``mase.executor`` 导入，避免把新逻辑写回根目录。
"""
from __future__ import annotations

import sys as _sys

from mase import executor as _impl

# 根模块和真实模块共享同一 module 对象，保证旧导入路径不会复制出第二份状态。
_sys.modules[__name__] = _impl
