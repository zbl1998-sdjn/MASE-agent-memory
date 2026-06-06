"""根目录兼容 shim，真实实现位于 ``mase.event_versioning``。

它服务于迁移前的事件版本导入路径；面试读代码时应跳到
`src/mase/event_versioning.py` 看当前实现。
"""
from __future__ import annotations

import sys as _sys

from mase import event_versioning as _impl

# 复用真实模块对象，避免兼容入口和稳定核心出现两套全局状态。
_sys.modules[__name__] = _impl
