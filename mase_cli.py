"""Compatibility shim. Real implementation: ``mase.mase_cli``.

Kept so legacy imports (``from mase_cli import X``) keep resolving.
New code should import from ``mase.mase_cli`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import mase_cli as _impl

# Alias both module names to the same object so attribute mutations and
# ``from mase_cli import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl

if __name__ == "__main__":  # pragma: no cover
    import runpy

    runpy.run_module("mase.mase_cli", run_name="__main__", alter_sys=True)
