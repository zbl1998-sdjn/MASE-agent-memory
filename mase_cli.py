"""根目录兼容 shim，真实实现位于 ``mase.mase_cli``。

保留根入口是为了让旧文档和脚本里的 ``python mase_cli.py`` 仍能运行；
新代码应使用包内 CLI。
"""
from __future__ import annotations

import sys as _sys

from mase import mase_cli as _impl

# 旧导入路径和包内路径共用同一模块对象，避免 CLI 全局状态分叉。
_sys.modules[__name__] = _impl

if __name__ == "__main__":  # pragma: no cover
    import runpy

    # 根脚本启动时转交给包内 CLI，确保行为与 `python -m mase.mase_cli` 一致。
    runpy.run_module("mase.mase_cli", run_name="__main__", alter_sys=True)
