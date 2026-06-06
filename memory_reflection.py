"""根目录兼容 shim，转发到 ``legacy_archive.memory_reflection``。

反思/摘要 helper 属于迁移前能力；保留完整导出是为了让历史测试和脚本
在 src/ 迁移后仍能工作。
"""
from __future__ import annotations

import sys as _sys

from legacy_archive import memory_reflection as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}
for _name in dir(_legacy):
    if _name not in _skip:
        # 包括下划线符号在内全部转发，避免隐式依赖断裂。
        setattr(_self, _name, getattr(_legacy, _name))

del _legacy, _self, _name, _skip, _sys
