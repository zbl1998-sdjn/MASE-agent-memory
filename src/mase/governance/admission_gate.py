"""Fact Admission Gate 纯函数(总纲 §4.3 的机械可执行子集)。

v1 实现 G2(可结构化)/ G3(secret·PII 基础正则检测)/ G5(tool_state 默认 TTL);
G1(证据)由 evidence_binder 承担,G4(冲突)在 fact_store,G0/G7 策略位默认放行。
纯函数不碰库;库操作与终态编排在 fact_store。

正则检测是"基础检测"(总纲 §8.2 原文口径):有漏报可能,漏报由 review 通道兜底;
模式集中于本文件常量,便于增补。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from .fact_contract import ClaimType, FactContract

DEFAULT_TTL_DAYS = 7

PASS = "pass"
QUARANTINE = "quarantine"
REJECT = "reject"

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "keyword_assignment": re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|private[_-]?key|access[_-]?key)\b\s*[:=]\s*\S+"
    ),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "pem_private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "cn_id_card": re.compile(r"(?<![\dA-Za-z])\d{17}[\dXx](?![\dA-Za-z])"),
    "cn_mobile": re.compile(r"(?<![\dA-Za-z])1[3-9]\d{9}(?![\dA-Za-z])"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


@dataclass(frozen=True)
class GateDecision:
    """一次门控判定;pattern 为命中的检测模式名(供脱敏与留痕)。"""

    action: str  # pass | quarantine | reject
    gate: str  # G2 | G3 | G5 …
    reason: str
    pattern: str | None = None


def check_structurable(contract: FactContract) -> GateDecision:
    """G2:subject-predicate-object 三元非空才可结构化。"""
    for field_name, value in (
        ("subject", contract.subject),
        ("predicate", contract.predicate),
        ("object", contract.object_value),
    ):
        if not value or not value.strip():
            return GateDecision(
                action=QUARANTINE,
                gate="G2",
                reason=f"不可结构化:{field_name} 为空",
            )
    return GateDecision(action=PASS, gate="G2", reason="subject-predicate-object 齐全")


def scan_sensitive(*texts: str) -> GateDecision:
    """G3:secret/token/私钥 → reject;PII → quarantine(review 兜底);全净 → pass。"""
    joined = [t for t in texts if t]
    for name, pattern in SECRET_PATTERNS.items():
        for text in joined:
            if pattern.search(text):
                return GateDecision(
                    action=REJECT,
                    gate="G3",
                    reason=f"疑似凭据/密钥(模式 {name}),policy 拒绝记忆",
                    pattern=name,
                )
    for name, pattern in PII_PATTERNS.items():
        for text in joined:
            if pattern.search(text):
                return GateDecision(
                    action=QUARANTINE,
                    gate="G3",
                    reason=f"疑似个人敏感信息(模式 {name}),需人工 review",
                    pattern=name,
                )
    return GateDecision(action=PASS, gate="G3", reason="未命中敏感模式")


def apply_ttl_policy(contract: FactContract) -> FactContract:
    """G5:tool_state 属临时状态,未显式给 valid_to 时自动设默认 TTL。"""
    if contract.claim_type != ClaimType.TOOL_STATE or contract.valid_to is not None:
        return contract
    base = _parse_ts(contract.observed_at) or datetime.now(timezone.utc)
    valid_to = (base + timedelta(days=DEFAULT_TTL_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return replace(contract, valid_to=valid_to)


def _parse_ts(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
