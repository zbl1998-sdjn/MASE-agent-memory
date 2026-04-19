"""Compatibility shim. Real implementation: ``mase.planner_agent``.

Layered fallback: serve attrs from ``mase.planner_agent`` first; for any name
that isn't there (e.g. ``InstructionPackage`` and other helpers tests still
import), fall back to ``legacy_archive.planner_agent``. This avoids the
src-migration leaving regression tests broken.
"""
from __future__ import annotations

import sys as _sys
from mase import planner_agent as _impl
from legacy_archive import planner_agent as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}

# Modern impl wins
for _name in dir(_impl):
    if _name not in _skip:
        setattr(_self, _name, getattr(_impl, _name))
# Fill missing with legacy (does not overwrite)
for _name in dir(_legacy):
    if _name in _skip or hasattr(_self, _name):
        continue
    setattr(_self, _name, getattr(_legacy, _name))

del _impl, _legacy, _self, _name, _skip, _sys
