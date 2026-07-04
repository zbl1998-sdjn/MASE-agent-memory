"""Retrieval contract primitives for Evidence Pack based recall."""

from __future__ import annotations

from dataclasses import dataclass

from .tenancy import NamespaceScope


@dataclass(frozen=True)
class RetrievalRequest:
    """Tenant-scoped recall request used by SDK/API boundary code."""

    query: str
    keywords: tuple[str, ...]
    scope: NamespaceScope = NamespaceScope()
    top_k: int = 8
