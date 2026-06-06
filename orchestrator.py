"""根目录兼容 shim，转发到 ``legacy_archive.orchestrator``。

V2 真实编排入口是 `mase.langgraph_orchestrator` 与 `mase.engine`；
这个文件只让旧 orchestrator 调用方继续运行。
"""
from __future__ import annotations

import sys as _sys

from legacy_archive import orchestrator as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}
for _name in dir(_legacy):
    if _name not in _skip:
        # 旧模块完整转发，确保迁移前脚本看到的符号没有缺口。
        setattr(_self, _name, getattr(_legacy, _name))

del _legacy, _self, _name, _skip, _sys
