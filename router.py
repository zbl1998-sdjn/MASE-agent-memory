"""根目录兼容 shim，真实实现位于 ``mase.router``。

保留它只是为了让旧脚本里的 ``from router import X`` 继续可用。
新代码应直接从 ``mase.router`` 导入，这样依赖方向才会回到 `src/mase` 稳定核心。
"""
from __future__ import annotations

import sys as _sys

from mase import router as _impl

# 把根模块名和真实模块名绑定到同一个对象；这样旧代码修改属性或
# ``from router import X`` 时，行为仍等价于迁移到 src/ 之前的布局。
_sys.modules[__name__] = _impl
