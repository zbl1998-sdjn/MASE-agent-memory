"""Compatibility shim. Real implementation: ``mase.reasoning_engine``.

Kept so legacy imports (``from reasoning_engine import X``) keep resolving.
New code should import from ``mase.reasoning_engine`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import reasoning_engine as _impl

# Alias both module names to the same object so attribute mutations and
# ``from reasoning_engine import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl
