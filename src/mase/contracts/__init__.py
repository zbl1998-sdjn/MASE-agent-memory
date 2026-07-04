"""Stable enterprise contract surface for MASE.

The current implementation keeps the canonical runtime code in
``mase.governance``.  This package gives enterprise integrations a stable import
location without forcing a breaking move of the legacy public surface.
"""

from __future__ import annotations

from .evidence import EvidenceLocator
from .fact_contract import ClaimType, EvidenceSpan, FactContract, FactStatus, TrustLevel
from .review import ReviewAction, ReviewDecision
from .tenancy import NamespaceScope

__all__ = [
    "ClaimType",
    "EvidenceLocator",
    "EvidenceSpan",
    "FactContract",
    "FactStatus",
    "NamespaceScope",
    "ReviewAction",
    "ReviewDecision",
    "TrustLevel",
]
