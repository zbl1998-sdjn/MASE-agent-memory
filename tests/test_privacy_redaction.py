from __future__ import annotations

from mase.audit_log import sanitize_audit_value
from mase.privacy import privacy_report, redact_value, scan_value


def test_privacy_scan_redacts_keys_and_inline_secrets() -> None:
    payload = {
        "authorization": "Bearer secret-token-value",
        "notes": "Contact alice@example.com with sk-testsecretsecretsecret",
    }

    findings = [finding.to_dict() for finding in scan_value(payload)]
    redacted = redact_value(payload)

    assert any(item["kind"] == "sensitive_key" for item in findings)
    assert any(item["kind"] == "email" for item in findings)
    assert redacted["authorization"] == "[REDACTED]"
    assert "alice@example.com" not in redacted["notes"]
    assert "sk-testsecretsecretsecret" not in redacted["notes"]


def test_audit_sanitizer_uses_privacy_redaction() -> None:
    sanitized = sanitize_audit_value(
        {
            "api_key": "sk-secretsecretsecretsecret",
            "metadata": {"comment": "email bob@example.com"},
        }
    )

    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["metadata"]["comment"] == "email [REDACTED:email]"


def test_privacy_report_returns_redacted_previews() -> None:
    report = privacy_report(
        [{"category": "user", "entity_value": "call me at user@example.com"}],
        source="facts",
    )

    assert report["finding_count"] == 1
    assert report["items"][0]["redacted_preview"]["entity_value"] == "call me at [REDACTED:email]"
