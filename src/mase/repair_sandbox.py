"""维修提案沙盒验证：只检查，不执行真实 mutation。"""

from __future__ import annotations

from typing import Any

from mase.repair_diff import MemoryReader


def _operation_pending_inputs(operation: dict[str, Any]) -> list[str]:
    """读取某个提案操作仍需人工补充的输入字段。"""
    return [str(item) for item in operation.get("requires") or [] if item]


def _check_fact_target(operation: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    """检查提案目标 fact 是否存在于当前 scope 的事实集中。"""
    target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
    category = target.get("category")
    entity_key = target.get("entity_key")
    if not category or not entity_key:
        return {"target_found": False, "reason": "target category/entity_key is incomplete"}
    found = any(row.get("category") == category and row.get("entity_key") == entity_key for row in facts)
    return {"target_found": found, "category": category, "entity_key": entity_key}


def run_repair_sandbox(case: dict[str, Any], memory: MemoryReader) -> dict[str, Any]:
    """验证 repair case 的 diff_proposal 是否具备执行条件。"""
    scope = dict(case.get("scope") or {})
    diff = case.get("diff_proposal") if isinstance(case.get("diff_proposal"), dict) else None
    blockers: list[str] = []
    warnings: list[str] = []
    if not scope:
        # 空 scope 不是硬阻断，但审批时必须特别关注租户/工作区/可见性边界。
        warnings.append("scope is empty; approval should require explicit tenant/workspace/visibility when available")
    if not diff:
        blockers.append("missing diff_proposal")
        return {
            "case_id": case.get("case_id"),
            "proposal_id": None,
            "scope": scope,
            "safe_to_execute": False,
            "execution_allowed": False,
            "mutation_count": 0,
            "blockers": blockers,
            "warnings": warnings,
            "operation_checks": [],
            "pending_inputs": [],
        }
    facts = memory.list_facts(scope_filters=scope)
    operations = [item for item in diff.get("proposed_operations") or [] if isinstance(item, dict)]
    if not operations:
        blockers.append("diff has no proposed_operations")
    operation_checks: list[dict[str, Any]] = []
    pending_inputs: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        required = _operation_pending_inputs(operation)
        if required:
            # 未解决人工输入的操作不能进入真实执行，即使其它检查都通过。
            pending_inputs.append(
                {
                    "operation_index": index,
                    "operation": operation.get("operation"),
                    "requires": required,
                }
            )
        check: dict[str, Any] = {
            "operation_index": index,
            "operation": operation.get("operation"),
            "status": "proposal_only",
            "would_mutate": False,
        }
        if operation.get("operation") == "propose_fact_supersede_or_upsert":
            # 这里只做目标存在性检查；真实 upsert/supersede 仍由审批后的执行层处理。
            check["fact_target"] = _check_fact_target(operation, facts)
        operation_checks.append(check)
    if pending_inputs:
        warnings.append("proposal still has unresolved manual inputs")
    return {
        "case_id": case.get("case_id"),
        "proposal_id": diff.get("proposal_id"),
        "scope": scope,
        # 沙盒永远不允许执行，只表达“如果审批通过是否看起来安全”。
        "safe_to_execute": not blockers and not pending_inputs,
        "execution_allowed": False,
        "mutation_count": 0,
        "blockers": blockers,
        "warnings": warnings,
        "operation_checks": operation_checks,
        "pending_inputs": pending_inputs,
        "validation": diff.get("validation") or {},
    }


__all__ = ["run_repair_sandbox"]
