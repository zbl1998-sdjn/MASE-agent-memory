from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_request
from integrations.openai_compat.runtime import memory_service
from integrations.openai_compat.schemas import (
    RepairCaseCreateRequest,
    RepairCaseExecutionRequest,
    RepairCaseTransitionRequest,
    RepairPlanRequest,
)
from mase.audit_log import append_audit_event
from mase.auth_policy import AuthContext, has_permission
from mase.repair_cases import (
    attach_repair_case_diff,
    attach_repair_case_execution,
    attach_repair_case_sandbox,
    create_repair_case,
    get_repair_case,
    list_repair_cases,
    transition_repair_case,
)
from mase.repair_diff import build_repair_diff
from mase.repair_execution import execute_repair_operations
from mase.repair_sandbox import run_repair_sandbox

router = APIRouter()


def _repair_steps(issue_type: str) -> list[str]:
    if issue_type == "recall_failure":
        return [
            "Run Recall Lab with the same scope and query.",
            "Inspect hit_inspections for stale/conflict/scope flags.",
            "Ask the memory agent to add or supersede only the unsupported fact.",
            "Re-run Recall Lab and Trace Studio to confirm the corrected evidence is selected.",
        ]
    if issue_type == "cost_spike":
        return [
            "Open Memory Observatory and identify provider/model/agent_role cost concentration.",
            "Check whether the call should use local fallback or a cheaper configured model.",
            "Ask the agent to propose a model-routing config diff, then review before applying.",
            "Re-run the same trace and compare model_call_summary.",
        ]
    return [
        "Locate the related event/fact in Write Inspector or Fact Center.",
        "Ask the memory agent to produce a minimal correction or supersede diff.",
        "Review scope, source_log_id and affected fact history before approving.",
        "Re-run Trace Studio and Recall Lab to validate the answer path.",
    ]


def build_repair_plan(req: RepairPlanRequest) -> dict[str, Any]:
    scope = scope_from_request(req)
    evidence = req.evidence or {}
    return {
        "issue_type": req.issue_type,
        "scope": scope,
        "symptom": req.symptom,
        "evidence": evidence,
        "risk_checklist": [
            "scope is explicit and matches the affected rows",
            "source evidence supports the proposed new fact",
            "old value is superseded rather than silently overwritten",
            "validation query is defined before the write",
        ],
        "recommended_steps": _repair_steps(req.issue_type),
        "agent_prompt": (
            "You are the MASE memory repair agent. Diagnose and repair only the memory issue below.\n"
            f"Issue type: {req.issue_type}\n"
            f"Scope: {json.dumps(scope, ensure_ascii=False)}\n"
            f"Symptom: {req.symptom}\n"
            f"Evidence: {json.dumps(evidence, ensure_ascii=False)}\n\n"
            "Rules:\n"
            "1. Do not invent facts; use only supplied evidence or ask for missing evidence.\n"
            "2. Prefer correction/supersede over destructive deletion.\n"
            "3. Preserve tenant/workspace/visibility scope exactly.\n"
            "4. Return a proposed diff, risk assessment, and validation query before writing.\n"
        ),
    }


def _audit_repair_case(
    auth: AuthContext,
    *,
    action: str,
    resource_id: str | None,
    outcome: str = "success",
    scope: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    append_audit_event(
        actor_id=auth.actor_id,
        role=auth.role,
        action=action,
        resource_type="repair_case",
        resource_id=resource_id,
        outcome=outcome,
        scope=scope or {},
        metadata=metadata or {},
    )


def _require_repair_approval(auth: AuthContext, *, case_id: str, status: str) -> None:
    if status not in {"approved", "executed"} or has_permission(auth, "repair_approve"):
        return
    _audit_repair_case(
        auth,
        action="repair_case.transition",
        resource_id=case_id,
        outcome="denied",
        metadata={"status": status, "reason": "missing repair_approve permission"},
    )
    raise HTTPException(status_code=403, detail="missing permission: repair_approve")


@router.post("/v1/ui/repair-plan")
def ui_repair_plan(req: RepairPlanRequest, _: AuthContext = Depends(require_permission("repair"))) -> dict[str, Any]:
    return response_object(
        "mase.ui.repair_plan",
        build_repair_plan(req),
        {"scope": scope_from_request(req), "generated_at": int(time.time())},
    )


@router.post("/v1/ui/repair-cases")
def ui_repair_case_create(
    req: RepairCaseCreateRequest,
    auth: AuthContext = Depends(require_permission("repair")),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    case = create_repair_case(
        issue_type=req.issue_type,
        symptom=req.symptom,
        evidence=req.evidence,
        scope=scope,
        actor_id=auth.actor_id,
    )
    _audit_repair_case(
        auth,
        action="repair_case.create",
        resource_id=str(case["case_id"]),
        scope=scope,
        metadata={"issue_type": req.issue_type, "status": case["status"]},
    )
    return response_object("mase.ui.repair_case", {"case": case}, {"scope": scope, "generated_at": int(time.time())})


@router.get("/v1/ui/repair-cases")
def ui_repair_cases(
    status: str | None = Query(default=None),
    issue_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthContext = Depends(require_permission("repair")),
) -> dict[str, Any]:
    payload = list_repair_cases(status=status, issue_type=issue_type, limit=limit)
    return response_object("mase.ui.repair_cases", payload, {"generated_at": int(time.time())})


@router.get("/v1/ui/repair-cases/{case_id}")
def ui_repair_case_detail(
    case_id: str,
    _: AuthContext = Depends(require_permission("repair")),
) -> dict[str, Any]:
    case = get_repair_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="repair_case_not_found")
    return response_object("mase.ui.repair_case", {"case": case}, {"generated_at": int(time.time())})


@router.post("/v1/ui/repair-cases/{case_id}/transition")
def ui_repair_case_transition(
    case_id: str,
    req: RepairCaseTransitionRequest,
    auth: AuthContext = Depends(require_permission("repair")),
) -> dict[str, Any]:
    _require_repair_approval(auth, case_id=case_id, status=req.status)
    try:
        case = transition_repair_case(
            case_id=case_id,
            status=req.status,
            actor_id=auth.actor_id,
            note=req.note,
            metadata=req.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="repair_case_not_found") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_repair_case(
        auth,
        action="repair_case.transition",
        resource_id=case_id,
        scope=case.get("scope") or {},
        metadata={"status": req.status, "note": req.note, "metadata": req.metadata or {}},
    )
    return response_object("mase.ui.repair_case", {"case": case}, {"generated_at": int(time.time())})


@router.post("/v1/ui/repair-cases/{case_id}/diff")
def ui_repair_case_diff(
    case_id: str,
    auth: AuthContext = Depends(require_permission("repair")),
) -> dict[str, Any]:
    case = get_repair_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="repair_case_not_found")
    diff = build_repair_diff(case, memory_service)
    try:
        updated = attach_repair_case_diff(case_id=case_id, diff=diff, actor_id=auth.actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_repair_case(
        auth,
        action="repair_case.diff",
        resource_id=case_id,
        scope=case.get("scope") or {},
        metadata={"proposal_id": diff.get("proposal_id"), "execution_allowed": False},
    )
    return response_object(
        "mase.ui.repair_case_diff",
        {"case": updated, "diff": diff},
        {"generated_at": int(time.time())},
    )


@router.post("/v1/ui/repair-cases/{case_id}/sandbox")
def ui_repair_case_sandbox(
    case_id: str,
    auth: AuthContext = Depends(require_permission("repair")),
) -> dict[str, Any]:
    case = get_repair_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="repair_case_not_found")
    report = run_repair_sandbox(case, memory_service)
    try:
        updated = attach_repair_case_sandbox(case_id=case_id, sandbox_report=report, actor_id=auth.actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_repair_case(
        auth,
        action="repair_case.sandbox",
        resource_id=case_id,
        scope=case.get("scope") or {},
        metadata={"proposal_id": report.get("proposal_id"), "safe_to_execute": report.get("safe_to_execute")},
    )
    return response_object(
        "mase.ui.repair_case_sandbox",
        {"case": updated, "sandbox": report},
        {"generated_at": int(time.time())},
    )


@router.post("/v1/ui/repair-cases/{case_id}/execute")
def ui_repair_case_execute(
    case_id: str,
    req: RepairCaseExecutionRequest,
    auth: AuthContext = Depends(require_permission("repair_approve")),
) -> dict[str, Any]:
    case = get_repair_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="repair_case_not_found")
    try:
        report = execute_repair_operations(
            case=case,
            operations=req.operations,
            confirm=req.confirm,
            memory=memory_service,
            actor_id=auth.actor_id,
            validation_query=req.validation_query,
        )
        updated = attach_repair_case_execution(case_id=case_id, execution_report=report, actor_id=auth.actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_repair_case(
        auth,
        action="repair_case.execute",
        resource_id=case_id,
        scope=case.get("scope") or {},
        metadata={"execution_id": report.get("execution_id"), "mutation_count": report.get("mutation_count")},
    )
    return response_object(
        "mase.ui.repair_case_execution",
        {"case": updated, "execution": report},
        {"generated_at": int(time.time())},
    )


__all__ = [
    "build_repair_plan",
    "router",
    "ui_repair_case_create",
    "ui_repair_case_detail",
    "ui_repair_case_diff",
    "ui_repair_case_execute",
    "ui_repair_case_sandbox",
    "ui_repair_case_transition",
    "ui_repair_cases",
    "ui_repair_plan",
]
