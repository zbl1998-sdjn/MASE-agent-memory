"""Review workflow contracts for governed memory facts."""

from __future__ import annotations

from dataclasses import dataclass


class ReviewAction:
    """Supported human review actions."""

    APPROVE = "approve"
    REJECT = "reject"
    RETRACT = "retract"
    EDIT = "edit"
    MERGE = "merge"


@dataclass(frozen=True)
class ReviewDecision:
    """A human or policy review decision.

    Reason is mandatory at API/UI boundaries; the dataclass keeps it explicit so
    review actions can be replayed from audit logs.
    """

    fact_id: str
    action: str
    reviewer: str
    reason: str
    target_fact_id: str | None = None
