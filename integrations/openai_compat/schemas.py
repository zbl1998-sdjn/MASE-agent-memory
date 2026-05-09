from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "mase"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class MemoryRecallRequest(BaseModel):
    query: str
    top_k: int = 5
    include_history: bool = False
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MemoryTimelineRequest(BaseModel):
    thread_id: str | None = None
    limit: int = 20
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MemoryEventRequest(BaseModel):
    thread_id: str
    role: str = "user"
    content: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MemoryCorrectionRequest(BaseModel):
    thread_id: str
    utterance: str
    extra_keywords: list[str] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class FactUpsertRequest(BaseModel):
    category: str
    key: str
    value: str
    reason: str | None = None
    source_log_id: int | None = None
    importance_score: float | None = None
    ttl_days: int | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class SessionStateRequest(BaseModel):
    session_id: str
    context_key: str
    context_value: str
    ttl_days: int | None = None
    metadata: dict[str, Any] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class ProcedureRequest(BaseModel):
    procedure_key: str
    content: str
    procedure_type: str = "rule"
    metadata: dict[str, Any] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class ConsolidateRequest(BaseModel):
    thread_id: str
    max_items: int = 50
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class RepairPlanRequest(BaseModel):
    issue_type: str = "incorrect_memory"
    symptom: str
    evidence: dict[str, Any] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class RepairCaseCreateRequest(BaseModel):
    issue_type: str = "incorrect_memory"
    symptom: str
    evidence: dict[str, Any] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class RepairCaseTransitionRequest(BaseModel):
    status: str
    note: str | None = None
    metadata: dict[str, Any] | None = None


class RepairCaseExecutionRequest(BaseModel):
    confirm: bool = False
    operations: list[dict[str, Any]]
    validation_query: str | None = None


class AnswerSupportRequest(BaseModel):
    answer: str
    query: str | None = None
    evidence: list[dict[str, Any]] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class RefusalQualityRequest(BaseModel):
    answer: str
    query: str | None = None
    evidence: list[dict[str, Any]] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class WhyNotRememberedRequest(BaseModel):
    query: str
    thread_id: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class SyntheticReplayRequest(BaseModel):
    cases: list[dict[str, Any]]
    top_k: int = 5
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class GoldenTestsRequest(BaseModel):
    cases: list[dict[str, Any]] | None = None
    top_k: int = 5
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class SloDashboardRequest(BaseModel):
    cases: list[dict[str, Any]] | None = None
    top_k: int = 5
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MaseRunRequest(BaseModel):
    query: str
    log: bool = False
