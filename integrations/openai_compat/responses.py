from __future__ import annotations

from typing import Any


def scope_from_request(req: Any) -> dict[str, Any]:
    return {
        key: value
        for key in ("tenant_id", "workspace_id", "visibility")
        if (value := getattr(req, key, None)) not in (None, "")
    }


def scope_from_query(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "visibility": visibility,
        }.items()
        if value not in (None, "")
    }


def response_object(object_name: str, data: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"object": object_name, "data": data}
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("_source") or row.get("source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts
