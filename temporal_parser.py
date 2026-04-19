"""Compatibility shim for the legacy temporal_parser helpers.

Re-exports ALL attributes (including underscore-prefixed private helpers
that `from x import *` would skip).
"""
from __future__ import annotations

import sys as _sys

from legacy_archive import temporal_parser as _legacy

_self = _sys.modules[__name__]
_skip = {"__name__", "__doc__", "__loader__", "__spec__",
         "__file__", "__path__", "__builtins__", "__package__"}
for _name in dir(_legacy):
    if _name not in _skip:
        setattr(_self, _name, getattr(_legacy, _name))

del _legacy, _self, _name, _skip, _sys
