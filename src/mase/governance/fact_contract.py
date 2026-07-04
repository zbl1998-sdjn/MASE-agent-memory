"""Compatibility re-exports for governed fact contracts.

The stable contract definitions now live in ``mase.contracts.fact_contract``.
This module remains so existing governance imports keep working during the
enterprise refactor.
"""

from __future__ import annotations

from mase.contracts.fact_contract import (
    SCHEMA_VERSION,
    ClaimType,
    EvidenceSpan,
    FactContract,
    FactStatus,
    TrustLevel,
    new_evidence_id,
    new_fact_id,
    utc_now,
)

__all__ = [
    "SCHEMA_VERSION",
    "ClaimType",
    "EvidenceSpan",
    "FactContract",
    "FactStatus",
    "TrustLevel",
    "new_evidence_id",
    "new_fact_id",
    "utc_now",
]
