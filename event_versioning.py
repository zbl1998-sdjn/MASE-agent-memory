"""Compatibility shim. Real implementation: ``mase.event_versioning``.

Kept so legacy imports (``from event_versioning import X``) keep resolving.
New code should import from ``mase.event_versioning`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import event_versioning as _impl

# Alias both module names to the same object so attribute mutations and
# ``from event_versioning import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl
