"""Evidence contract helpers used by enterprise boundary code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceLocator:
    """Stable pointer to a source span.

    Invariant:
        ``span_start`` and ``span_end`` are offsets into the source text when
        present.  A missing span is allowed for review records, but such
        evidence must not make a fact active.
    """

    source_type: str
    source_id: str
    span_start: int | None = None
    span_end: int | None = None
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
