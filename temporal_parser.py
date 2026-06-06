"""根目录兼容 shim，转发到 ``legacy_archive.temporal_parser``。

当前时间线/事件版本能力在 `src/mase` 中演进；旧日期解析 helper
仅作为兼容表面保留。
"""
from __future__ import annotations

import sys as _sys

from legacy_archive import temporal_parser as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}
for _name in dir(_legacy):
    if _name not in _skip:
        # 转发旧 helper，避免历史 benchmark 脚本的隐式导入失败。
        setattr(_self, _name, getattr(_legacy, _name))

del _legacy, _self, _name, _skip, _sys
