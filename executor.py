"""Compatibility shim. Real implementation: ``mase.executor``.

Kept so legacy imports (``from executor import X``) keep resolving.
New code should import from ``mase.executor`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import executor as _impl

# Alias both module names to the same object so attribute mutations and
# ``from executor import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl
