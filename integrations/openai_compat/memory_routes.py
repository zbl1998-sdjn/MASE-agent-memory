"""记忆 API 路由：召回、时间线、事实、纠错和归并。

读接口允许按 scope 查询；写接口必须通过 `require_write_access`，
并在成功后写审计事件，保证演示环境和真实工作区的边界一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from integrations.openai_compat.auth_dependencies import require_write_access
from integrations.openai_compat.responses import (
    response_object,
    scope_from_query,
    scope_from_request,
    source_counts,
)
from integrations.openai_compat.runtime import memory_service
from integrations.openai_compat.schemas import (
    ConsolidateRequest,
    FactUpsertRequest,
    GovernanceFactEditRequest,
    GovernanceFactMergeRequest,
    GovernanceReviewActionRequest,
    MemoryCorrectionRequest,
    MemoryEventRequest,
    MemoryRecallRequest,
    MemoryTimelineRequest,
    ProcedureRequest,
    SessionStateRequest,
)
from mase.audit_log import append_audit_event
from mase.auth_policy import AuthContext, default_auth_context
from mase.governance.fact_store import (
    approve_fact,
    edit_fact,
    get_fact,
    list_review_queue,
    merge_facts,
    reject_fact,
    retract_fact,
)
from mase.governance.fact_store import (
    list_facts as list_governance_facts,
)
from mase.governance.write_facade import GovernedFactWriteFacade
from mase_tools.memory.db_core import PROFILE_TEMPLATES

router = APIRouter()


def _auth_for_audit(auth: Any) -> AuthContext:
    """把依赖注入结果规整成审计上下文。"""
    return auth if isinstance(auth, AuthContext) else default_auth_context()


def _audit_success(
    auth: Any,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    scope: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """写入成功后记录统一审计事件，便于 UI 和日志追踪。"""
    context = _auth_for_audit(auth)
    append_audit_event(
        actor_id=context.actor_id,
        role=context.role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        scope=scope,
        metadata=metadata,
    )


def _governance_scope_args(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": scope.get("tenant_id"),
        "workspace_id": scope.get("workspace_id"),
        "visibility": scope.get("visibility"),
    }


def _reviewer(req: Any, auth: AuthContext) -> str:
    return str(getattr(req, "reviewer", None) or auth.actor_id)


def _ensure_governance_fact_in_scope(fact_id: str, scope: dict[str, Any]) -> dict[str, Any]:
    fact = get_fact(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail=f"fact_not_found:{fact_id}")
    for key, expected in scope.items():
        if expected is not None and fact.get(key) != expected:
            raise HTTPException(status_code=404, detail=f"fact_not_found_in_scope:{fact_id}")
    return fact


@router.post("/v1/memory/recall")
def memory_recall(req: MemoryRecallRequest) -> dict[str, Any]:
    """按关键词/全文查询召回事件与事实证据。"""
    scope = scope_from_request(req)
    hits = memory_service.search_memory(
        req.query.split(),
        full_query=req.query,
        limit=req.top_k,
        include_history=req.include_history,
        scope_filters=scope,
    )
    return {
        "object": "mase.memory.recall",
        "data": hits,
        "metadata": {"scope": scope, "result_count": len(hits), "source_counts": source_counts(hits)},
    }


@router.post("/v1/memory/current-state")
def memory_current_state(req: MemoryRecallRequest) -> dict[str, Any]:
    """只召回当前事实表，适合回答“现在是什么状态”。"""
    scope = scope_from_request(req)
    hits = memory_service.recall_current_state(req.query.split(), limit=req.top_k, scope_filters=scope)
    return {
        "object": "mase.memory.current_state",
        "data": hits,
        "metadata": {"scope": scope, "result_count": len(hits), "source_counts": source_counts(hits)},
    }


@router.post("/v1/memory/timeline")
def memory_timeline(req: MemoryTimelineRequest) -> dict[str, Any]:
    """POST 版本时间线接口，方便前端用 JSON body 传 scope。"""
    scope = scope_from_request(req)
    rows = memory_service.recall_timeline(thread_id=req.thread_id, limit=req.limit, scope_filters=scope)
    return {
        "object": "mase.memory.timeline",
        "data": rows,
        "metadata": {"scope": scope, "result_count": len(rows)},
    }


@router.get("/v1/memory/timeline")
def memory_timeline_get(
    thread_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=500),
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """GET 版本时间线接口，方便浏览器地址栏和轻量脚本调试。"""
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    rows = memory_service.recall_timeline(thread_id=thread_id, limit=limit, scope_filters=scope)
    return response_object(
        "mase.memory.timeline",
        rows,
        {"scope": scope, "result_count": len(rows)},
    )


@router.post("/v1/memory/events")
def memory_event(req: MemoryEventRequest, auth: AuthContext = Depends(require_write_access)) -> dict[str, Any]:
    """追加一条事件日志；这是长期记忆的 append-only 入口。"""
    scope = scope_from_request(req)
    result = memory_service.remember_event(
        req.thread_id,
        req.role,
        req.content,
        scope_filters=scope,
    )
    _audit_success(
        auth,
        action="memory.event.create",
        resource_type="memory_event",
        resource_id=str(result.get("log_id") or result.get("id") or req.thread_id),
        scope=scope,
        metadata={"thread_id": req.thread_id, "role": req.role},
    )
    return response_object("mase.memory.event", result, {"scope": scope})


@router.post("/v1/memory/corrections")
def memory_correction(req: MemoryCorrectionRequest, auth: AuthContext = Depends(require_write_access)) -> dict[str, Any]:
    """记录纠错并触发旧事实 supersede/新事实写入链路。"""
    scope = scope_from_request(req)
    result = memory_service.correct_memory(
        req.thread_id,
        req.utterance,
        extra_keywords=req.extra_keywords,
        scope_filters=scope,
    )
    _audit_success(
        auth,
        action="memory.correction.create",
        resource_type="memory_correction",
        resource_id=req.thread_id,
        scope=scope,
        metadata={"thread_id": req.thread_id, "extra_keyword_count": len(req.extra_keywords or [])},
    )
    return response_object("mase.memory.correction", result, {"scope": scope})


@router.get("/v1/memory/facts")
def memory_facts(
    category: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """列出当前事实表，category 可选过滤。"""
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    rows = memory_service.list_facts(category=category, scope_filters=scope)
    return response_object(
        "mase.memory.facts",
        rows,
        {"scope": scope, "result_count": len(rows), "profile_templates": PROFILE_TEMPLATES},
    )


@router.post("/v1/memory/facts")
def memory_fact_upsert(req: FactUpsertRequest, auth: AuthContext = Depends(require_write_access)) -> dict[str, Any]:
    """显式写入/覆盖当前事实；category/key 是幂等边界。"""
    scope = scope_from_request(req)
    result = memory_service.upsert_fact(
        req.category,
        req.key,
        req.value,
        reason=req.reason,
        source_log_id=req.source_log_id,
        importance_score=req.importance_score,
        ttl_days=req.ttl_days,
        scope_filters=scope,
    )
    _audit_success(
        auth,
        action="memory.fact.upsert",
        resource_type="memory_fact",
        resource_id=f"{req.category}:{req.key}",
        scope=scope,
        metadata={"category": req.category, "entity_key": req.key, "source_log_id": req.source_log_id},
    )
    return response_object("mase.memory.fact", result, {"scope": scope})


@router.get("/v1/memory/facts/history")
def memory_fact_history(
    category: str | None = None,
    entity_key: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """查看事实槽位的历史版本，用于解释覆盖和过期。"""
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    rows = memory_service.get_fact_history(
        category=category,
        entity_key=entity_key,
        limit=limit,
        scope_filters=scope,
    )
    return response_object("mase.memory.fact_history", rows, {"scope": scope, "result_count": len(rows)})


@router.delete("/v1/memory/facts/{category}/{entity_key}")
def memory_fact_forget(
    category: str,
    entity_key: str,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    auth: AuthContext = Depends(require_write_access),
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    result = memory_service.forget(
        category=category,
        entity_key=entity_key,
        scope_filters=scope,
    )
    _audit_success(
        auth,
        action="memory.fact.forget",
        resource_type="memory_fact",
        resource_id=f"{category}:{entity_key}",
        scope=scope,
        metadata={"deleted_count": result.get("deleted_count")},
    )
    return response_object("mase.memory.forget_fact", result, {"scope": scope})


@router.get("/v1/memory/governance/review-queue")
def memory_governance_review_queue(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """列出治理层待人工裁决事实，带证据与冲突上下文。"""
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    rows = list_review_queue(**_governance_scope_args(scope))
    return response_object(
        "mase.memory.governance.review_queue",
        rows,
        {"scope": scope, "result_count": len(rows)},
    )


@router.get("/v1/memory/governance/facts")
def memory_governance_facts(
    entity_id: str | None = None,
    status: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """列出治理层 FactContract 行；这是旧 entity_state CRUD 之外的可证明事实视图。"""
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    rows = list_governance_facts(
        entity_id=entity_id,
        status=status,
        **_governance_scope_args(scope),
    )
    return response_object(
        "mase.memory.governance.facts",
        rows,
        {"scope": scope, "result_count": len(rows)},
    )


@router.get("/v1/memory/governance/shadow-diff")
def memory_governance_shadow_diff(
    category: str | None = None,
    entity_key: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """Compare legacy entity_state with governed fact rows during dual-write cutover."""
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    report = GovernedFactWriteFacade().shadow_read_diff(
        category=category,
        key=entity_key,
        scope_filters=scope,
    )
    return response_object(
        "mase.memory.governance.shadow_diff",
        report,
        {"scope": scope},
    )


@router.post("/v1/memory/governance/facts/{fact_id}/approve")
def memory_governance_fact_approve(
    fact_id: str,
    req: GovernanceReviewActionRequest,
    auth: AuthContext = Depends(require_write_access),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    _ensure_governance_fact_in_scope(fact_id, scope)
    ok, message = approve_fact(fact_id, reviewer=_reviewer(req, auth), reason=req.reason)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    _audit_success(
        auth,
        action="memory.governance_fact.approve",
        resource_type="governance_fact",
        resource_id=fact_id,
        scope=scope,
        metadata={"reason": req.reason},
    )
    return response_object("mase.memory.governance.fact_action", {"fact_id": fact_id, "action": "approve", "message": message})


@router.post("/v1/memory/governance/facts/{fact_id}/reject")
def memory_governance_fact_reject(
    fact_id: str,
    req: GovernanceReviewActionRequest,
    auth: AuthContext = Depends(require_write_access),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    _ensure_governance_fact_in_scope(fact_id, scope)
    ok, message = reject_fact(fact_id, reviewer=_reviewer(req, auth), reason=req.reason)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    _audit_success(
        auth,
        action="memory.governance_fact.reject",
        resource_type="governance_fact",
        resource_id=fact_id,
        scope=scope,
        metadata={"reason": req.reason},
    )
    return response_object("mase.memory.governance.fact_action", {"fact_id": fact_id, "action": "reject", "message": message})


@router.post("/v1/memory/governance/facts/{fact_id}/retract")
def memory_governance_fact_retract(
    fact_id: str,
    req: GovernanceReviewActionRequest,
    auth: AuthContext = Depends(require_write_access),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    _ensure_governance_fact_in_scope(fact_id, scope)
    ok = retract_fact(fact_id, req.reason or "manual retract", reviewer=_reviewer(req, auth))
    if not ok:
        raise HTTPException(status_code=404, detail=f"fact_not_found:{fact_id}")
    _audit_success(
        auth,
        action="memory.governance_fact.retract",
        resource_type="governance_fact",
        resource_id=fact_id,
        scope=scope,
        metadata={"reason": req.reason},
    )
    return response_object("mase.memory.governance.fact_action", {"fact_id": fact_id, "action": "retract"})


@router.post("/v1/memory/governance/facts/{fact_id}/edit")
def memory_governance_fact_edit(
    fact_id: str,
    req: GovernanceFactEditRequest,
    auth: AuthContext = Depends(require_write_access),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    _ensure_governance_fact_in_scope(fact_id, scope)
    ok, message, new_fact = edit_fact(
        fact_id,
        reviewer=_reviewer(req, auth),
        reason=req.reason,
        subject=req.subject,
        predicate=req.predicate,
        object_value=req.object_value,
        evidence_text=req.evidence_text,
        source_full_text=req.source_full_text,
        source_type=req.source_type,
        source_id=req.source_id,
        trust_level=req.trust_level,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    _audit_success(
        auth,
        action="memory.governance_fact.edit",
        resource_type="governance_fact",
        resource_id=fact_id,
        scope=scope,
        metadata={"new_fact_id": (new_fact or {}).get("fact_id"), "reason": req.reason},
    )
    return response_object(
        "mase.memory.governance.fact_action",
        {"fact_id": fact_id, "action": "edit", "message": message, "new_fact": new_fact},
    )


@router.post("/v1/memory/governance/facts/{fact_id}/merge")
def memory_governance_fact_merge(
    fact_id: str,
    req: GovernanceFactMergeRequest,
    auth: AuthContext = Depends(require_write_access),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    _ensure_governance_fact_in_scope(fact_id, scope)
    _ensure_governance_fact_in_scope(req.target_fact_id, scope)
    ok, message = merge_facts(
        fact_id,
        req.target_fact_id,
        reviewer=_reviewer(req, auth),
        reason=req.reason,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    _audit_success(
        auth,
        action="memory.governance_fact.merge",
        resource_type="governance_fact",
        resource_id=fact_id,
        scope=scope,
        metadata={"target_fact_id": req.target_fact_id, "reason": req.reason},
    )
    return response_object(
        "mase.memory.governance.fact_action",
        {"fact_id": fact_id, "action": "merge", "target_fact_id": req.target_fact_id, "message": message},
    )


@router.get("/v1/memory/session-state/{session_id}")
def memory_session_state_get(
    session_id: str,
    include_expired: bool = False,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    rows = memory_service.get_session_state(
        session_id,
        include_expired=include_expired,
        scope_filters=scope,
    )
    return response_object("mase.memory.session_state", rows, {"scope": scope, "result_count": len(rows)})


@router.post("/v1/memory/session-state")
def memory_session_state_upsert(req: SessionStateRequest, auth: AuthContext = Depends(require_write_access)) -> dict[str, Any]:
    scope = scope_from_request(req)
    result = memory_service.upsert_session_state(
        req.session_id,
        req.context_key,
        req.context_value,
        ttl_days=req.ttl_days,
        metadata=req.metadata,
        scope_filters=scope,
    )
    _audit_success(
        auth,
        action="memory.session_state.upsert",
        resource_type="session_state",
        resource_id=f"{req.session_id}:{req.context_key}",
        scope=scope,
        metadata={"session_id": req.session_id, "context_key": req.context_key, "ttl_days": req.ttl_days},
    )
    return response_object("mase.memory.session_state_upsert", result, {"scope": scope})


@router.delete("/v1/memory/session-state/{session_id}")
def memory_session_state_forget(
    session_id: str,
    context_key: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    auth: AuthContext = Depends(require_write_access),
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    result = memory_service.forget(
        session_id=session_id,
        context_key=context_key,
        scope_filters=scope,
    )
    _audit_success(
        auth,
        action="memory.session_state.forget",
        resource_type="session_state",
        resource_id=f"{session_id}:{context_key or '*'}",
        scope=scope,
        metadata={"session_id": session_id, "context_key": context_key, "deleted_count": result.get("deleted_count")},
    )
    return response_object("mase.memory.forget_session_state", result, {"scope": scope})


@router.get("/v1/memory/procedures")
def memory_procedures(
    procedure_type: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    rows = memory_service.list_procedures(procedure_type=procedure_type, scope_filters=scope)
    return response_object("mase.memory.procedures", rows, {"scope": scope, "result_count": len(rows)})


@router.post("/v1/memory/procedures")
def memory_procedure_register(req: ProcedureRequest, auth: AuthContext = Depends(require_write_access)) -> dict[str, Any]:
    scope = scope_from_request(req)
    result = memory_service.register_procedure(
        req.procedure_key,
        req.content,
        procedure_type=req.procedure_type,
        metadata=req.metadata,
        scope_filters=scope,
    )
    _audit_success(
        auth,
        action="memory.procedure.register",
        resource_type="memory_procedure",
        resource_id=req.procedure_key,
        scope=scope,
        metadata={"procedure_type": req.procedure_type},
    )
    return response_object("mase.memory.procedure", result, {"scope": scope})


@router.get("/v1/memory/snapshots")
def memory_snapshots(
    thread_id: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    rows = memory_service.list_episodic_snapshots(thread_id=thread_id, scope_filters=scope)
    return response_object("mase.memory.snapshots", rows, {"scope": scope, "result_count": len(rows)})


@router.post("/v1/memory/snapshots/consolidate")
def memory_snapshot_consolidate(req: ConsolidateRequest, auth: AuthContext = Depends(require_write_access)) -> dict[str, Any]:
    scope = scope_from_request(req)
    result = memory_service.consolidate_session(
        req.thread_id,
        max_items=req.max_items,
        scope_filters=scope,
    )
    _audit_success(
        auth,
        action="memory.snapshot.consolidate",
        resource_type="memory_snapshot",
        resource_id=str(result.get("snapshot_id") or req.thread_id),
        scope=scope,
        metadata={"thread_id": req.thread_id, "max_items": req.max_items},
    )
    return response_object("mase.memory.snapshot", result, {"scope": scope})


@router.get("/v1/memory/validate")
def memory_validate(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    scope = scope_from_query(tenant_id, workspace_id, visibility)
    return response_object("mase.memory.validation", memory_service.validate_memory(scope_filters=scope))


@router.post("/v1/memory/explain")
def memory_explain(req: MemoryRecallRequest) -> dict[str, Any]:
    scope = scope_from_request(req)
    payload = memory_service.explain_memory_answer(req.query, limit=req.top_k, scope_filters=scope)
    return {"object": "mase.memory.explain", "data": payload, "metadata": payload.get("metadata", {})}
