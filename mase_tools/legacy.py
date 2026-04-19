"""Compatibility shim for the legacy helper surface.

The benchmark runner and a number of regression tests still import
``mase_tools.legacy``. During the modular split, the implementation stayed in
``legacy_archive/legacy.py`` but this import path disappeared, which breaks the
existing benchmark/test entrypoints. Re-exporting here restores the original
surface without changing runtime behavior.

NOTE: ``from legacy_archive.legacy import *`` skips underscore-prefixed names
because they're considered private. Many regression tests (and the orchestrator)
import private helpers like ``_build_aggregation_notes`` directly. To restore
the original surface verbatim, we copy *every* module attribute (including
underscore names) from the source module into our namespace.
"""

from __future__ import annotations

import sys as _sys

from legacy_archive import legacy as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}
for _name in dir(_legacy):
    if _name in _skip:
        continue
    setattr(_self, _name, getattr(_legacy, _name))

del _legacy, _self, _name, _sys, _skip
