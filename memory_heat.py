"""根目录兼容 shim，转发到 ``legacy_archive.memory_heat``。

V2 的热记忆/模式判断已拆到 `src/mase/mode_selector.py` 等模块；
这里仅保证旧 helper 仍可导入。
"""
from __future__ import annotations

import sys as _sys

from legacy_archive import memory_heat as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}
for _name in dir(_legacy):
    if _name not in _skip:
        # 旧 helper 表面按原样导出，迁移期不做行为改写。
        setattr(_self, _name, getattr(_legacy, _name))

del _legacy, _self, _name, _skip, _sys
