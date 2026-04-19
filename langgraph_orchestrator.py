"""Compatibility shim. Real implementation: ``mase.langgraph_orchestrator``.

Kept so legacy imports (``from langgraph_orchestrator import X``) keep resolving.
New code should import from ``mase.langgraph_orchestrator`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import langgraph_orchestrator as _impl

# Alias both module names to the same object so attribute mutations and
# ``from langgraph_orchestrator import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl

if __name__ == "__main__":  # pragma: no cover
    import runpy

    runpy.run_module("mase.langgraph_orchestrator", run_name="__main__", alter_sys=True)
