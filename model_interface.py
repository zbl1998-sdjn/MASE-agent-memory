"""根目录兼容 shim，真实实现位于 ``mase.model_interface``。

`ModelInterface` 是模型供应商、调用账本和 HTTP 协议层的公共门面；
根目录文件仅保留旧导入路径，不承载新逻辑。
"""
from __future__ import annotations

import sys as _sys

from mase import model_interface as _impl

# 保持模块对象别名，避免旧导入路径看到不同的 provider/cache/ledger 状态。
_sys.modules[__name__] = _impl
