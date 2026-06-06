"""根目录兼容 shim，真实实现位于 ``mase.topic_threads``。

topic/thread 分桶会影响长期记忆召回边界；面试讲实现时应读
`src/mase/topic_threads.py`。
"""
from __future__ import annotations

import sys as _sys

from mase import topic_threads as _impl

# 兼容层只做 module alias，确保旧导入路径不会创建第二套 thread 状态。
_sys.modules[__name__] = _impl
