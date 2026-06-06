"""根目录兼容 shim，转发到 ``legacy_archive.planner``。

这个文件不是 V2 规划器；它保留迁移前 helper 的完整导出，
包括普通 ``from x import *`` 会跳过的下划线内部符号。
"""
from __future__ import annotations

import sys as _sys

from legacy_archive import planner as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}
for _name in dir(_legacy):
    if _name not in _skip:
        # 精确复制旧模块表面，避免历史测试依赖的私有 helper 丢失。
        setattr(_self, _name, getattr(_legacy, _name))

del _legacy, _self, _name, _skip, _sys
