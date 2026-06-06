"""脱敏与隐私扫描工具，供 trace、成本中心和导出面使用。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SENSITIVE_KEY_PARTS = ("authorization", "api_key", "apikey", "password", "secret", "token", "headers")
SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE)),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("generic_secret", re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[^'\"\s]{8,}", re.IGNORECASE)),
    ("credit_card_like", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
)


@dataclass(frozen=True)
class PrivacyFinding:
    """一次敏感字段或敏感文本模式命中。"""

    path: str
    kind: str
    preview: str
    severity: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "preview": self.preview,
            "severity": self.severity,
        }


def is_sensitive_key(key: str) -> bool:
    """按字段名判断是否应视为敏感。"""
    normalized = key.lower().replace("-", "_")
    return (
        any(part in normalized for part in SENSITIVE_KEY_PARTS)
        or normalized.endswith("_api_key")
        or normalized.endswith("_secret")
        or normalized.endswith("_password")
        or normalized in {"access_token", "refresh_token", "id_token"}
    )


def redact_text(value: str) -> str:
    """按正则模式脱敏字符串内容。"""
    redacted = value
    for kind, pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(f"[REDACTED:{kind}]", redacted)
    return redacted


def redact_value(value: Any, *, drop_sensitive_keys: bool = False) -> Any:
    """递归脱敏结构化值。"""
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if is_sensitive_key(key_text):
                # drop_sensitive_keys 用于导出场景；默认保留键名但隐藏值，便于审计字段形状。
                if not drop_sensitive_keys:
                    output[key_text] = "[REDACTED]"
                continue
            output[key_text] = redact_value(item, drop_sensitive_keys=drop_sensitive_keys)
        return output
    if isinstance(value, list):
        return [redact_value(item, drop_sensitive_keys=drop_sensitive_keys) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, drop_sensitive_keys=drop_sensitive_keys) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def scan_value(value: Any, *, path: str = "$") -> list[PrivacyFinding]:
    """递归扫描结构化值中的敏感键和敏感文本。"""
    findings: list[PrivacyFinding] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            next_path = f"{path}.{key_text}"
            if is_sensitive_key(key_text):
                # 字段名本身敏感时，即使值为空也记录 finding。
                findings.append(PrivacyFinding(path=next_path, kind="sensitive_key", preview=key_text))
            findings.extend(scan_value(item, path=next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(scan_value(item, path=f"{path}[{index}]"))
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            findings.extend(scan_value(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        for kind, pattern in SENSITIVE_PATTERNS:
            for match in pattern.finditer(value):
                findings.append(PrivacyFinding(path=path, kind=kind, preview=redact_text(match.group(0))))
    return findings


def privacy_report(items: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    """为一组结构化行生成隐私扫描报告和脱敏预览。"""
    rows: list[dict[str, Any]] = []
    total_findings = 0
    for index, item in enumerate(items):
        findings = [finding.to_dict() for finding in scan_value(item, path=f"$.{source}[{index}]")]
        if not findings:
            continue
        total_findings += len(findings)
        rows.append(
            {
                "source": source,
                "index": index,
                "finding_count": len(findings),
                "findings": findings,
                "redacted_preview": redact_value(item),
            }
        )
    return {
        "source": source,
        "item_count": len(items),
        "finding_count": total_findings,
        "items": rows,
    }


__all__ = [
    "PrivacyFinding",
    "is_sensitive_key",
    "privacy_report",
    "redact_text",
    "redact_value",
    "scan_value",
]
