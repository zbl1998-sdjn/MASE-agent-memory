"""Compatibility shim. Real implementation: ``mase.notetaker_agent``.

Kept so legacy imports (``from notetaker_agent import X``) keep resolving.
New code should import from ``mase.notetaker_agent`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import notetaker_agent as _impl

# Alias both module names to the same object so attribute mutations and
# ``from notetaker_agent import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl
