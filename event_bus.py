"""根目录兼容 shim，转发到 ``legacy_archive.event_bus``。

当前产品事件总线实现位于 `src/mase/event_bus.py`；此文件只服务
迁移前的事件快照消费者。
"""
from __future__ import annotations

import sys as _sys

from legacy_archive import event_bus as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}
for _name in dir(_legacy):
    if _name not in _skip:
        # 保留旧模块的完整导出表面，包括测试可能直接调用的内部 helper。
        setattr(_self, _name, getattr(_legacy, _name))

del _legacy, _self, _name, _skip, _sys
