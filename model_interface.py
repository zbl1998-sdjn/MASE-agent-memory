"""Compatibility shim. Real implementation: ``mase.model_interface``.

Kept so legacy imports (``from model_interface import X``) keep resolving.
New code should import from ``mase.model_interface`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import model_interface as _impl

# Alias both module names to the same object so attribute mutations and
# ``from model_interface import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl
