"""Compatibility shim. Real implementation: ``mase.topic_threads``.

Kept so legacy imports (``from topic_threads import X``) keep resolving.
New code should import from ``mase.topic_threads`` directly.
"""
from __future__ import annotations

import sys as _sys

from mase import topic_threads as _impl

# Alias both module names to the same object so attribute mutations and
# ``from topic_threads import X`` behave identically to the pre-migration layout.
_sys.modules[__name__] = _impl
