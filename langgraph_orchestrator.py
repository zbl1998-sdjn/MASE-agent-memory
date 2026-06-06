"""根目录兼容 shim，真实实现位于 ``mase.langgraph_orchestrator``。

这个入口仍支持旧脚本导入和 ``python langgraph_orchestrator.py`` 启动；
真实编排逻辑不在这里维护。
"""
from __future__ import annotations

import sys as _sys

from mase import langgraph_orchestrator as _impl

# 绑定到真实模块对象，旧路径和新路径看到的是同一份编排实现。
_sys.modules[__name__] = _impl

if __name__ == "__main__":  # pragma: no cover
    import runpy

    # 作为脚本执行时继续委托给真实模块的 __main__ 分支。
    runpy.run_module("mase.langgraph_orchestrator", run_name="__main__", alter_sys=True)
