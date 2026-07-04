"""Central governed fact lifecycle rules."""

from __future__ import annotations

from dataclasses import dataclass

from mase.contracts.fact_contract import FactStatus


class InvalidFactTransition(ValueError):
    """Raised when a fact lifecycle move violates the governed state machine."""


@dataclass(frozen=True)
class FactTransition:
    """A validated state transition for audit and replay.

    Boundary:
        This object is pure policy data.  It does not write the database; storage
        layers must validate a transition here before mutating fact state.
    """

    fact_id: str
    from_status: str
    to_status: str
    reason_code: str
    actor_id: str | None = None
    request_id: str | None = None


class FactStateMachine:
    """Central authority for governed fact lifecycle transitions.

    Invariant:
        A fact may only become active after the write path has bound evidence and
        passed admission checks.  This class enforces the status graph; callers
        remain responsible for evidence checks before requesting activation.
    """

    _ALLOWED: dict[str, frozenset[str]] = {
        FactStatus.CANDIDATE: frozenset({FactStatus.ACTIVE, FactStatus.QUARANTINED, FactStatus.REJECTED}),
        FactStatus.QUARANTINED: frozenset({FactStatus.ACTIVE, FactStatus.REJECTED, FactStatus.RETRACTED}),
        FactStatus.ACTIVE: frozenset({FactStatus.SUPERSEDED, FactStatus.EXPIRED, FactStatus.RETRACTED}),
        FactStatus.SUPERSEDED: frozenset({FactStatus.RETRACTED}),
        FactStatus.EXPIRED: frozenset({FactStatus.RETRACTED}),
        FactStatus.REJECTED: frozenset(),
        FactStatus.RETRACTED: frozenset(),
    }

    def validate(self, transition: FactTransition) -> FactTransition:
        """Return the transition when allowed, otherwise raise.

        Raises:
            InvalidFactTransition: if either state is unknown or the edge is not
                in the governed lifecycle graph.
        """
        if transition.from_status not in self._ALLOWED:
            raise InvalidFactTransition(f"unknown from_status: {transition.from_status!r}")
        if transition.to_status not in FactStatus.ALL:
            raise InvalidFactTransition(f"unknown to_status: {transition.to_status!r}")
        if transition.to_status not in self._ALLOWED[transition.from_status]:
            raise InvalidFactTransition(
                f"cannot move fact {transition.fact_id} from "
                f"{transition.from_status} to {transition.to_status}"
            )
        if not transition.reason_code:
            raise InvalidFactTransition("reason_code is required")
        return transition

    def can_transition(self, from_status: str, to_status: str) -> bool:
        """Return whether a transition is allowed without raising."""
        return to_status in self._ALLOWED.get(from_status, frozenset())
