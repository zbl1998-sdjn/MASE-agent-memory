"""OpenAI 兼容 API 的请求模型。

这些类只描述 HTTP 边界的输入形状；业务校验和权限判断在路由/服务层执行。
字段名保持英文是外部 API 契约，中文注释解释用途但不改协议。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """OpenAI 消息列表的最小兼容形状。"""

    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """`/v1/chat/completions` 请求；stream 字段用于兼容客户端能力探测。"""

    model: str = "mase"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class MemoryRecallRequest(BaseModel):
    """记忆召回请求，scope 字段贯穿租户/工作区/可见性隔离。"""

    query: str
    top_k: int = 5
    include_history: bool = False
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MemoryTimelineRequest(BaseModel):
    """按 thread 或全局 scope 读取事件时间线。"""

    thread_id: str | None = None
    limit: int = 20
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MemoryEventRequest(BaseModel):
    """追加一条记忆事件；写入路由会额外要求 write 权限。"""

    thread_id: str
    role: str = "user"
    content: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MemoryCorrectionRequest(BaseModel):
    """用户纠错入口，extra_keywords 用来帮助定位被纠正的旧记忆。"""

    thread_id: str
    utterance: str
    extra_keywords: list[str] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class FactUpsertRequest(BaseModel):
    """当前事实表 upsert 请求；category/key 共同构成事实槽位。"""

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
    """短期/会话状态写入请求，适合保存当前工作台上下文。"""

    session_id: str
    context_key: str
    context_value: str
    ttl_days: int | None = None
    metadata: dict[str, Any] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class ProcedureRequest(BaseModel):
    """过程性记忆请求，例如规则、偏好流程或工具使用步骤。"""

    procedure_key: str
    content: str
    procedure_type: str = "rule"
    metadata: dict[str, Any] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class ConsolidateRequest(BaseModel):
    """把事件日志归并为结构化事实的请求。"""

    thread_id: str
    max_items: int = 50
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class RepairPlanRequest(BaseModel):
    """生成修复计划的请求，不直接执行变更。"""

    issue_type: str = "incorrect_memory"
    symptom: str
    evidence: dict[str, Any] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class RepairCaseCreateRequest(BaseModel):
    """创建可审计修复工单的请求。"""

    issue_type: str = "incorrect_memory"
    symptom: str
    evidence: dict[str, Any] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class RepairCaseTransitionRequest(BaseModel):
    """修复工单状态流转请求。"""

    status: str
    note: str | None = None
    metadata: dict[str, Any] | None = None


class RepairCaseExecutionRequest(BaseModel):
    """执行修复工单的请求；confirm=False 时保持试运行语义。"""

    confirm: bool = False
    operations: list[dict[str, Any]]
    validation_query: str | None = None


class AnswerSupportRequest(BaseModel):
    """回答证据支撑视图请求，用于检查回答片段是否有证据。"""

    answer: str
    query: str | None = None
    evidence: list[dict[str, Any]] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class RefusalQualityRequest(BaseModel):
    """拒答质量分析请求，用于区分合理拒答和过度拒答。"""

    answer: str
    query: str | None = None
    evidence: list[dict[str, Any]] | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class WhyNotRememberedRequest(BaseModel):
    """“为什么没记住”诊断请求。"""

    query: str
    thread_id: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class SyntheticReplayRequest(BaseModel):
    """合成回放用例批量执行请求。"""

    cases: list[dict[str, Any]]
    top_k: int = 5
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class GoldenTestsRequest(BaseModel):
    """黄金测试请求；cases 为空时使用内置发布门禁样本。"""

    cases: list[dict[str, Any]] | None = None
    top_k: int = 5
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class SloDashboardRequest(BaseModel):
    """SLO 仪表盘请求，复用黄金用例评估召回可靠性。"""

    cases: list[dict[str, Any]] | None = None
    top_k: int = 5
    tenant_id: str | None = None
    workspace_id: str | None = None
    visibility: str | None = None


class MaseRunRequest(BaseModel):
    """完整 MASE 编排请求；log 控制是否写入记忆。"""

    query: str
    log: bool = False
