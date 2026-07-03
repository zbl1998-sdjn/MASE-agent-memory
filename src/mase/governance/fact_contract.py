"""FactContract v1 数据对象:治理层"可证明事实"的结构化契约。

对齐 MASE_whitebox_memory_governance_plan.md §4.1/§4.2.3/§5.1(v1 最小字段)。
纯数据对象,不持有连接;读写经 fact_store(唯一写入口,状态机在彼处强制)。
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "fact_contract.v1"


class FactStatus:
    """状态机全集;expired 字段就位,TTL 执行留 P1。"""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ALL = frozenset(
        {CANDIDATE, ACTIVE, QUARANTINED, SUPERSEDED, RETRACTED, REJECTED, EXPIRED}
    )


class TrustLevel:
    """证据信任等级(总纲 §4.2.3):E5 用户显式陈述 → E0 可疑输入。"""

    E0 = 0  # prompt injection / 可疑输入 → 安全审计
    E1 = 1  # 单次 LLM 推断 → 只能 quarantine
    E2 = 2  # 多来源一致派生摘要 → 需 review
    E3 = 3  # 工具实时观测 → 需 TTL + tool trace
    E4 = 4  # 可信文件中的明确文本 → 需 span/哈希
    E5 = 5  # 用户显式陈述 / 人工确认


class ClaimType:
    """v1 声明类型;inference 一律不可直接 active(总纲 §4.1.2)。"""

    PREFERENCE = "preference"
    PROFILE = "profile"
    PROJECT_FACT = "project_fact"
    DOCUMENT_CLAIM = "document_claim"
    TOOL_STATE = "tool_state"
    INFERENCE = "inference"
    ALL = frozenset(
        {PREFERENCE, PROFILE, PROJECT_FACT, DOCUMENT_CLAIM, TOOL_STATE, INFERENCE}
    )


def new_fact_id() -> str:
    return f"fact_{uuid.uuid4().hex}"


def new_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class EvidenceSpan:
    """来源全文中的机械可验引文;span 为 None 表示定位失败(隔离态证据)。"""

    evidence_id: str
    source_type: str  # media_extraction | memory_log | file | manual_entry
    source_id: str
    span_start: int | None
    span_end: int | None
    quote_hash: str  # sha256(命中原文段)
    quote_excerpt: str | None  # ≤200 字符引文,人读;完整原文经 source 反查
    trust_level: int
    created_at: str

    def to_row(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "quote_hash": self.quote_hash,
            "quote_excerpt": self.quote_excerpt,
            "trust_level": self.trust_level,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> EvidenceSpan:
        return cls(
            evidence_id=row["evidence_id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            span_start=row["span_start"],
            span_end=row["span_end"],
            quote_hash=row["quote_hash"],
            quote_excerpt=row["quote_excerpt"],
            trust_level=row["trust_level"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class FactContract:
    """一条长期事实的完整契约;行键与 facts 表列一一对应(object_value ↔ object 列)。"""

    fact_id: str
    entity_id: str
    claim_type: str
    subject: str
    predicate: str
    object_value: str
    confidence: float
    observed_at: str
    qualifiers: dict[str, Any] | None = None
    status: str = FactStatus.CANDIDATE
    confidence_basis: dict[str, Any] | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    visibility: str = "private"
    sensitivity: str = "normal"
    schema_version: str = SCHEMA_VERSION
    tenant_id: str = ""
    workspace_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "entity_id": self.entity_id,
            "claim_type": self.claim_type,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object_value,
            "qualifiers_json": _dump_json(self.qualifiers),
            "status": self.status,
            "confidence": self.confidence,
            "confidence_basis_json": _dump_json(self.confidence_basis),
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "observed_at": self.observed_at,
            "visibility": self.visibility,
            "sensitivity": self.sensitivity,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> FactContract:
        return cls(
            fact_id=row["fact_id"],
            entity_id=row["entity_id"],
            claim_type=row["claim_type"],
            subject=row["subject"],
            predicate=row["predicate"],
            object_value=row["object"],
            confidence=row["confidence"],
            observed_at=row["observed_at"],
            qualifiers=_load_json(row["qualifiers_json"]),
            status=row["status"],
            confidence_basis=_load_json(row["confidence_basis_json"]),
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            visibility=row["visibility"],
            sensitivity=row["sensitivity"],
            schema_version=row["schema_version"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _dump_json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise TypeError(f"qualifiers/confidence_basis 必须是 JSON object,得到: {type(loaded).__name__}")
    return loaded
