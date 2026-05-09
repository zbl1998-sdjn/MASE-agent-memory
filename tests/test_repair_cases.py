from __future__ import annotations

import pytest

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


def test_repair_case_lifecycle_is_append_only_and_queryable(tmp_path):
    path = tmp_path / "repair_cases.jsonl"
    case = create_repair_case(
        issue_type="recall_failure",
        symptom="wrong project codename",
        evidence={"trace_id": "trace-1", "api_key": "secret-value"},
        scope={"tenant_id": "tenant-a", "workspace_id": "workspace-a"},
        actor_id="operator-a",
        path=path,
    )

    assert case["status"] == "open"
    assert case["evidence"]["api_key"] == "[REDACTED]"
    diagnosed = transition_repair_case(
        case_id=case["case_id"],
        status="diagnosed",
        actor_id="operator-a",
        note="stale fact selected",
        path=path,
    )

    assert diagnosed["status"] == "diagnosed"
    assert len(diagnosed["events"]) == 2
    assert get_repair_case(case["case_id"], path=path)["status"] == "diagnosed"

    payload = list_repair_cases(status="diagnosed", path=path)
    assert payload["summary"]["total_count"] == 1
    assert payload["summary"]["by_status"]["diagnosed"] == 1
    assert payload["cases"][0]["case_id"] == case["case_id"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_repair_case_rejects_invalid_transitions(tmp_path):
    path = tmp_path / "repair_cases.jsonl"
    case = create_repair_case(
        issue_type="incorrect_memory",
        symptom="bad preference",
        actor_id="operator-a",
        path=path,
    )

    with pytest.raises(ValueError, match="open -> approved"):
        transition_repair_case(case_id=case["case_id"], status="approved", actor_id="operator-a", path=path)

    with pytest.raises(KeyError):
        transition_repair_case(case_id="missing", status="diagnosed", actor_id="operator-a", path=path)


def test_repair_diff_is_proposal_only_and_attached_to_case(tmp_path):
    path = tmp_path / "repair_cases.jsonl"
    case = create_repair_case(
        issue_type="incorrect_memory",
        symptom="project codename remembered as old budget",
        scope={"tenant_id": "tenant-a"},
        actor_id="operator-a",
        path=path,
    )

    class MemoryReader:
        def list_facts(self, category=None, *, scope_filters=None):
            del category, scope_filters
            return [
                {
                    "category": "project",
                    "entity_key": "codename",
                    "entity_value": "old budget",
                    "source_log_id": 7,
                }
            ]

        def recall_timeline(self, *, thread_id=None, limit=50, scope_filters=None):
            del thread_id, limit, scope_filters
            return [{"id": 7, "thread_id": "thread-a", "content": "old budget codename"}]

        def get_fact_history(self, *, category=None, entity_key=None, limit=50, scope_filters=None):
            del category, entity_key, limit, scope_filters
            return [{"category": "project", "entity_key": "codename", "new_value": "old budget"}]

    diff = build_repair_diff(case, MemoryReader())
    updated = attach_repair_case_diff(case_id=case["case_id"], diff=diff, actor_id="operator-a", path=path)

    assert diff["execution_allowed"] is False
    assert diff["proposed_operations"][0]["operation"] == "propose_fact_supersede_or_upsert"
    assert updated["status"] == "diagnosed"
    assert updated["diff_proposal"]["proposal_id"] == diff["proposal_id"]
    assert updated["events"][-1]["action"] == "diff_proposed"

    report = run_repair_sandbox(updated, MemoryReader())
    sandboxed = attach_repair_case_sandbox(
        case_id=case["case_id"],
        sandbox_report=report,
        actor_id="operator-a",
        path=path,
    )

    assert report["execution_allowed"] is False
    assert report["mutation_count"] == 0
    assert report["pending_inputs"]
    assert sandboxed["sandbox_report"]["proposal_id"] == diff["proposal_id"]
    assert sandboxed["events"][-1]["action"] == "sandbox_validated"


def test_repair_execution_requires_approval_and_explicit_confirmation(tmp_path):
    path = tmp_path / "repair_cases.jsonl"
    case = create_repair_case(
        issue_type="incorrect_memory",
        symptom="project owner is wrong",
        scope={"tenant_id": "tenant-a"},
        actor_id="operator-a",
        path=path,
    )
    diff = {"proposal_id": "diff-1", "proposed_operations": [{"operation": "upsert_fact"}]}
    attach_repair_case_diff(case_id=case["case_id"], diff=diff, actor_id="operator-a", path=path)
    sandboxed = attach_repair_case_sandbox(
        case_id=case["case_id"],
        sandbox_report={"proposal_id": "diff-1", "safe_to_execute": True},
        actor_id="operator-a",
        path=path,
    )
    approved = transition_repair_case(
        case_id=sandboxed["case_id"],
        status="pending_approval",
        actor_id="operator-a",
        path=path,
    )
    approved = transition_repair_case(case_id=approved["case_id"], status="approved", actor_id="approver-a", path=path)

    class MemoryWriter:
        def upsert_fact(self, category, key, value, **kwargs):
            return {"category": category, "key": key, "value": value, "scope": kwargs.get("scope_filters")}

        def correct_memory(self, thread_id, utterance, **kwargs):
            return {"thread_id": thread_id, "utterance": utterance, "scope": kwargs.get("scope_filters")}

    with pytest.raises(ValueError, match="confirm=true"):
        execute_repair_operations(
            case=approved,
            operations=[{"operation": "upsert_fact"}],
            confirm=False,
            memory=MemoryWriter(),
            actor_id="approver-a",
        )

    report = execute_repair_operations(
        case=approved,
        operations=[
            {
                "operation": "upsert_fact",
                "category": "project",
                "entity_key": "owner",
                "entity_value": "alice",
                "reason": "repair_execution",
            }
        ],
        confirm=True,
        memory=MemoryWriter(),
        actor_id="approver-a",
        validation_query="Who owns the project?",
    )
    executed = attach_repair_case_execution(
        case_id=approved["case_id"],
        execution_report=report,
        actor_id="approver-a",
        path=path,
    )

    assert report["mutation_count"] == 1
    assert report["operations"][0]["result"]["scope"] == {"tenant_id": "tenant-a"}
    assert executed["status"] == "executed"
    assert executed["execution_report"]["execution_id"] == report["execution_id"]
