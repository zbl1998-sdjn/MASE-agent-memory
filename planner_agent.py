"""根目录兼容 shim，主实现位于 ``mase.planner_agent``。

这里比普通 shim 多一层兼容：优先导出 `src/mase` 的现代 Planner，
缺失的旧符号再从 `legacy_archive.planner_agent` 补齐，保护历史测试和脚本。
"""
from __future__ import annotations

import sys as _sys

from legacy_archive import planner_agent as _legacy
from mase import planner_agent as _impl

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}

# 现代实现优先，保证新 Planner 的公共 API 覆盖旧实现。
for _name in dir(_impl):
    if _name not in _skip:
        setattr(_self, _name, getattr(_impl, _name))
# 旧实现只补缺口，不覆盖现代实现已有符号。
for _name in dir(_legacy):
    if _name in _skip or hasattr(_self, _name):
        continue
    setattr(_self, _name, getattr(_legacy, _name))

del _impl, _legacy, _self, _name, _skip, _sys
