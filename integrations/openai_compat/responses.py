"""OpenAI 兼容路由共用的响应和 scope 小工具。"""
from __future__ import annotations

from typing import Any


def scope_from_request(req: Any) -> dict[str, Any]:
    """从 Pydantic request 中抽取租户/工作区/可见性过滤条件。"""
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
    """从 query 参数中抽取 scope；空字符串不进入过滤条件。"""
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
    """统一返回 `{object, data, metadata}`，便于前端按 object 分发。"""
    payload = {"object": object_name, "data": data}
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """统计召回来源分布，用于 UI 展示证据来自 facts/history/trace 等位置。"""
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("_source") or row.get("source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts
