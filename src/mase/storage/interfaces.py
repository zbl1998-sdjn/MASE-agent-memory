"""Protocol interfaces for future SQLite/PostgreSQL storage backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mase.contracts.fact_contract import FactContract


@dataclass(frozen=True)
class FactRecord:
    """Storage-neutral fact row with evidence identifiers."""

    fact: FactContract
    evidence_ids: tuple[str, ...]


class StorageRepository(Protocol):
    """Governed memory storage contract.

    Implementations may use SQLite, PostgreSQL, or a test double, but they must
    preserve tenant scope and fact lifecycle invariants.
    """

    def put_fact(self, fact: FactContract, evidence_ids: tuple[str, ...]) -> None:
        """Persist a governed fact and its supporting evidence IDs."""

    def get_fact(self, fact_id: str) -> FactRecord | None:
        """Return a fact record by ID."""

    def list_facts(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        status: str | None = None,
    ) -> list[FactRecord]:
        """List facts with explicit tenant/workspace filters."""
