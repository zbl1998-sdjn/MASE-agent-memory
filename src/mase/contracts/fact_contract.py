"""FactContract v1 data contract for governed memory facts."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "fact_contract.v1"


def utc_now() -> str:
    """Return the canonical governance timestamp format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FactStatus:
    """Governed fact lifecycle states."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ALL = frozenset(
        {CANDIDATE, ACTIVE, QUARANTINED, SUPERSEDED, RETRACTED, REJECTED, EXPIRED}
    )


class TrustLevel:
    """Evidence trust ladder used by admission and conflict resolution."""

    E0 = 0
    E1 = 1
    E2 = 2
    E3 = 3
    E4 = 4
    E5 = 5


class ClaimType:
    """Supported long-term memory claim types."""

    PREFERENCE = "preference"
    PROFILE = "profile"
    PROJECT_FACT = "project_fact"
    DOCUMENT_CLAIM = "document_claim"
    TOOL_STATE = "tool_state"
    INFERENCE = "inference"
    ALL = frozenset(
        {PREFERENCE, PROFILE, PROJECT_FACT, DOCUMENT_CLAIM, TOOL_STATE, INFERENCE}
    )


def new_fact_id() -> str:
    """Return a globally unique fact identifier."""
    return f"fact_{uuid.uuid4().hex}"


def new_evidence_id() -> str:
    """Return a globally unique evidence identifier."""
    return f"ev_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class EvidenceSpan:
    """A mechanically verifiable span in source text."""

    evidence_id: str
    source_type: str
    source_id: str
    span_start: int | None
    span_end: int | None
    quote_hash: str
    quote_excerpt: str | None
    trust_level: int
    created_at: str

    def to_row(self) -> dict[str, Any]:
        """Serialize the span for SQLite storage."""
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "quote_hash": self.quote_hash,
            "quote_excerpt": self.quote_excerpt,
            "trust_level": self.trust_level,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> EvidenceSpan:
        """Deserialize a storage row."""
        return cls(
            evidence_id=row["evidence_id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            span_start=row["span_start"],
            span_end=row["span_end"],
            quote_hash=row["quote_hash"],
            quote_excerpt=row["quote_excerpt"],
            trust_level=row["trust_level"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class FactContract:
    """A long-term governed memory fact.

    Invariants:
        Runtime write paths may create active facts only after evidence binding
        succeeds.  The contract is pure data and does not perform admission.
    """

    fact_id: str
    entity_id: str
    claim_type: str
    subject: str
    predicate: str
    object_value: str
    confidence: float
    observed_at: str
    qualifiers: dict[str, Any] | None = None
    status: str = FactStatus.CANDIDATE
    confidence_basis: dict[str, Any] | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    visibility: str = "private"
    sensitivity: str = "normal"
    schema_version: str = SCHEMA_VERSION
    tenant_id: str = ""
    workspace_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_row(self) -> dict[str, Any]:
        """Serialize the contract to the canonical facts table shape."""
        return {
            "fact_id": self.fact_id,
            "entity_id": self.entity_id,
            "claim_type": self.claim_type,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object_value,
            "qualifiers_json": _dump_json(self.qualifiers),
            "status": self.status,
            "confidence": self.confidence,
            "confidence_basis_json": _dump_json(self.confidence_basis),
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "observed_at": self.observed_at,
            "visibility": self.visibility,
            "sensitivity": self.sensitivity,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> FactContract:
        """Deserialize a facts table row."""
        return cls(
            fact_id=row["fact_id"],
            entity_id=row["entity_id"],
            claim_type=row["claim_type"],
            subject=row["subject"],
            predicate=row["predicate"],
            object_value=row["object"],
            confidence=row["confidence"],
            observed_at=row["observed_at"],
            qualifiers=_load_json(row["qualifiers_json"]),
            status=row["status"],
            confidence_basis=_load_json(row["confidence_basis_json"]),
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            visibility=row["visibility"],
            sensitivity=row["sensitivity"],
            schema_version=row["schema_version"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _dump_json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise TypeError(f"qualifiers/confidence_basis must be a JSON object, got {type(loaded).__name__}")
    return loaded
