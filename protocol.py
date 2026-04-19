"""Compatibility shim. Real implementation: ``mase.protocol``.

Kept so legacy imports (``from protocol import X``) keep resolving.
New code should import from ``mase.protocol`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import protocol as _impl

# Alias both module names to the same object so attribute mutations and
# ``from protocol import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl
