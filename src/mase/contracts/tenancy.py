"""Tenant and namespace contract helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NamespaceScope:
    """Tenant/workspace/visibility scope used by local and enterprise modes.

    Empty tenant/workspace values represent the local single-user namespace.
    Enterprise callers should always pass explicit tenant and workspace values.
    """

    tenant_id: str = ""
    workspace_id: str = ""
    visibility: str = "private"

    def to_filters(self) -> dict[str, str]:
        """Return non-empty scope filters for existing APIs."""
        filters: dict[str, str] = {"visibility": self.visibility or "private"}
        if self.tenant_id:
            filters["tenant_id"] = self.tenant_id
        if self.workspace_id:
            filters["workspace_id"] = self.workspace_id
        return filters
