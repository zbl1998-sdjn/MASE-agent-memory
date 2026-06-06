"""根目录兼容 shim，真实实现位于 ``mase.protocol``。

agent 消息协议属于稳定核心；根目录文件只为旧导入路径兜底。
"""
from __future__ import annotations

import sys as _sys

from mase import protocol as _impl

# 通过 module alias 保持旧路径和新路径读取同一个协议对象集合。
_sys.modules[__name__] = _impl
