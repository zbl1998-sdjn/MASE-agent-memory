"""审批后的 repair operation 执行器。"""

from __future__ import annotations

import uuid
from typing import Any, Protocol


class MemoryWriter(Protocol):
    """repair 执行所需的写接口。"""

    def upsert_fact(
        self,
        category: str,
        key: str,
        value: str,
        *,
        reason: str | None = None,
        source_log_id: int | None = None,
        importance_score: float | None = None,
        ttl_days: int | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def correct_memory(
        self,
        thread_id: str,
        utterance: str,
        *,
        extra_keywords: list[str] | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


SUPPORTED_REPAIR_OPERATIONS = ("upsert_fact", "correct_memory")


def _require_text(payload: dict[str, Any], *keys: str) -> str:
    """从多个别名字段中读取必填文本。"""
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    raise ValueError(f"missing required field: {'/'.join(keys)}")


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    """读取可选整数字段。"""
    value = payload.get(key)
    if value in (None, ""):
        return None
    return int(value)


def _validate_case_ready(case: dict[str, Any], *, confirm: bool, operations: list[dict[str, Any]]) -> None:
    """执行前的硬门禁：已审批、显式确认、提案和沙盒报告齐全。"""
    if case.get("status") != "approved":
        raise ValueError("repair execution requires an approved case")
    if not confirm:
        raise ValueError("repair execution requires confirm=true")
    if not isinstance(case.get("diff_proposal"), dict):
        raise TypeError("repair execution requires a diff_proposal")
    if not isinstance(case.get("sandbox_report"), dict):
        raise TypeError("repair execution requires a sandbox_report")
    if not operations:
        raise ValueError("repair execution requires at least one operation")
    for operation in operations:
        if operation.get("operation") not in SUPPORTED_REPAIR_OPERATIONS:
            # 只允许白名单操作，避免 proposal 字段被当成任意方法调用。
            raise ValueError(f"unsupported repair operation: {operation.get('operation')}")


def execute_repair_operations(
    *,
    case: dict[str, Any],
    operations: list[dict[str, Any]],
    confirm: bool,
    memory: MemoryWriter,
    actor_id: str,
    validation_query: str | None = None,
) -> dict[str, Any]:
    """执行已审批 repair 操作，并返回审计报告。"""
    _validate_case_ready(case, confirm=confirm, operations=operations)
    scope = dict(case.get("scope") or {})
    results: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        operation_name = operation.get("operation")
        if operation_name == "upsert_fact":
            # upsert_fact 只写入当前 case scope，来源/TTL/重要度由 proposal 显式给出。
            result = memory.upsert_fact(
                _require_text(operation, "category"),
                _require_text(operation, "entity_key", "key"),
                _require_text(operation, "entity_value", "value"),
                reason=str(operation.get("reason") or "repair_execution"),
                source_log_id=_optional_int(operation, "source_log_id"),
                importance_score=operation.get("importance_score"),
                ttl_days=operation.get("ttl_days"),
                scope_filters=scope,
            )
        elif operation_name == "correct_memory":
            # correct_memory 保留 thread_id，并把额外关键词传给底层纠错日志。
            keywords = operation.get("extra_keywords")
            result = memory.correct_memory(
                _require_text(operation, "thread_id"),
                _require_text(operation, "corrected_utterance", "utterance"),
                extra_keywords=keywords if isinstance(keywords, list) else None,
                scope_filters=scope,
            )
        else:  # pragma: no cover - protected by validation
            raise ValueError(f"unsupported repair operation: {operation_name}")
        results.append({"operation_index": index, "operation": operation_name, "result": result})
    return {
        "execution_id": f"exec_{uuid.uuid4().hex[:16]}",
        "case_id": case.get("case_id"),
        "proposal_id": case.get("diff_proposal", {}).get("proposal_id"),
        "actor_id": actor_id,
        "scope": scope,
        "mutation_count": len(results),
        "operations": results,
        "validation_query": validation_query,
    }


__all__ = ["SUPPORTED_REPAIR_OPERATIONS", "execute_repair_operations"]
