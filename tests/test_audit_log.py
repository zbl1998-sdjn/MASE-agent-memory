from __future__ import annotations

from pathlib import Path

from mase.audit_log import append_audit_event, list_audit_events


def test_audit_log_appends_sanitized_jsonl_events(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"

    event = append_audit_event(
        actor_id="alice",
        role="operator",
        action="memory.fact.upsert",
        resource_type="memory_fact",
        resource_id="profile:name",
        scope={"tenant_id": "tenant-a"},
        metadata={"authorization": "Bearer secret", "summary": "ok"},
        path=path,
    )

    result = list_audit_events(path=path)

    assert event["audit_id"]
    assert result["events"][0]["actor_id"] == "alice"
    assert result["events"][0]["metadata"]["authorization"] == "[REDACTED]"
    assert result["events"][0]["metadata"]["summary"] == "ok"


def test_audit_log_filters_and_skips_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    append_audit_event(
        actor_id="alice",
        role="operator",
        action="memory.event.create",
        resource_type="memory_event",
        path=path,
    )
    append_audit_event(
        actor_id="bob",
        role="auditor",
        action="auth.permission_denied",
        resource_type="permission",
        outcome="denied",
        path=path,
    )
    path.write_text(path.read_text(encoding="utf-8") + "{bad json\n", encoding="utf-8")

    result = list_audit_events(actor_id="bob", path=path)

    assert len(result["events"]) == 1
    assert result["events"][0]["actor_id"] == "bob"
    assert result["metadata"]["skipped_count"] == 1
