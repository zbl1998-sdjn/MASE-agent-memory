"""Compatibility shim. Real implementation: ``mase.router``.

Kept so legacy imports (``from router import X``) keep resolving.
New code should import from ``mase.router`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import router as _impl

# Alias both module names to the same object so attribute mutations and
# ``from router import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl
