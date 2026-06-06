"""根目录兼容 shim，真实实现位于 ``mase.reasoning_engine``。

推理链路是 benchmark/长上下文问答的重要能力，真实代码在 `src/mase`；
这里不应继续承载产品逻辑。
"""
from __future__ import annotations

import sys as _sys

from mase import reasoning_engine as _impl

# 别名到真实模块，避免根 shim 和包内模块的全局配置出现不一致。
_sys.modules[__name__] = _impl
