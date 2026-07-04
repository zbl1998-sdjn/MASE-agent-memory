from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "governance.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    monkeypatch.setenv("MASE_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    return db


def _fact(subject: str, predicate: str, value: str, *, tenant_id: str = "tenant-a", workspace_id: str = "ws-a"):
    from mase.governance.fact_contract import FactContract, new_fact_id

    return FactContract(
        fact_id=new_fact_id(),
        entity_id="project:p4",
        claim_type="project_fact",
        subject=subject,
        predicate=predicate,
        object_value=value,
        confidence=0.9,
        observed_at="2026-07-04T00:00:00Z",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility="shared",
    )


def _propose(contract, evidence: str, trust: int = 5):
    from mase.governance.fact_store import propose_fact

    return propose_fact(
        contract,
        evidence,
        source_type="manual_entry",
        source_id=contract.fact_id,
        trust_level=trust,
        source_full_text=f"Evidence says {evidence}.",
    )


def test_governance_review_routes_approve_reject_edit_merge_and_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_db(tmp_path, monkeypatch)
    from integrations.openai_compat.memory_routes import (
        memory_governance_fact_approve,
        memory_governance_fact_edit,
        memory_governance_fact_merge,
        memory_governance_fact_reject,
        memory_governance_fact_retract,
        memory_governance_facts,
        memory_governance_review_queue,
    )
    from integrations.openai_compat.schemas import (
        GovernanceFactEditRequest,
        GovernanceFactMergeRequest,
        GovernanceReviewActionRequest,
    )

    scope = {"tenant_id": "tenant-a", "workspace_id": "ws-a", "visibility": "shared"}
    old = _propose(_fact("project", "owner", "Alice"), "owner Alice", trust=5)
    quarantined = _propose(_fact("project", "owner", "Bob"), "owner Bob", trust=1)
    rejected = _propose(_fact("project", "owner", "Carol"), "owner Carol", trust=1)
    target = _propose(_fact("project", "backup_owner", "Dana"), "backup_owner Dana", trust=5)

    queue = memory_governance_review_queue(**scope)
    assert any(row["fact_id"] == quarantined.fact_id for row in queue["data"])

    approved = memory_governance_fact_approve(
        quarantined.fact_id,
        GovernanceReviewActionRequest(reason="verified by reviewer", reviewer="reviewer-a", **scope),
    )
    assert approved["data"]["action"] == "approve"

    rejected_payload = memory_governance_fact_reject(
        rejected.fact_id,
        GovernanceReviewActionRequest(reason="wrong value", reviewer="reviewer-a", **scope),
    )
    assert rejected_payload["data"]["action"] == "reject"

    edited = memory_governance_fact_edit(
        target.fact_id,
        GovernanceFactEditRequest(
            object_value="Dana S.",
            evidence_text="backup_owner Dana S.",
            source_full_text="Evidence says backup_owner Dana S.",
            reason="normalize name",
            reviewer="reviewer-a",
            **scope,
        ),
    )
    assert edited["data"]["new_fact"]["object"] == "Dana S."

    merged = memory_governance_fact_merge(
        old.fact_id,
        GovernanceFactMergeRequest(target_fact_id=quarantined.fact_id, reason="duplicate winner", reviewer="reviewer-a", **scope),
    )
    assert merged["data"]["target_fact_id"] == quarantined.fact_id

    retracted = memory_governance_fact_retract(
        quarantined.fact_id,
        GovernanceReviewActionRequest(reason="policy removal", reviewer="reviewer-a", **scope),
    )
    assert retracted["data"]["action"] == "retract"

    facts = memory_governance_facts(**scope)
    assert facts["metadata"]["scope"] == scope
    audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "memory.governance_fact.approve" in audit_text
    assert "memory.governance_fact.edit" in audit_text
    assert "memory.governance_fact.merge" in audit_text


def test_document_claim_sheet_evaluation_and_stale_marking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _isolate_db(tmp_path, monkeypatch)
    from mase.governance.document_claims import (
        evaluate_document_claims,
        list_document_claims,
        mark_document_claims_stale,
        render_document_claim_sheet,
    )
    from mase.governance.fact_contract import ClaimType, FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact
    from mase_tools.memory.api import mase2_record_extraction, mase2_register_media_asset

    media_id = mase2_register_media_asset(
        "a" * 64,
        source_uri="file://policy.pdf",
        media_type="application/pdf",
        page_count=2,
    )
    extraction_id = mase2_record_extraction(
        media_id,
        extractor_name="unit",
        model_name="none",
        extractor_version="1",
        full_text="line one\nThe policy limit is 42.\nline three",
        result_json=json.dumps({"ok": True}),
    )
    fact = propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="media:" + "a" * 12,
            claim_type=ClaimType.DOCUMENT_CLAIM,
            subject="policy",
            predicate="limit",
            object_value="42",
            confidence=0.9,
            observed_at="2026-07-04T00:00:00Z",
            qualifiers={"scope": "policy.pdf", "page": 2},
        ),
        "policy limit is 42",
        source_type="media_extraction",
        source_id=str(extraction_id),
        trust_level=4,
        source_full_text="line one\nThe policy limit is 42.\nline three",
    )

    claims = list_document_claims(source_id=str(extraction_id), db_path=db)
    assert claims[0]["fact_id"] == fact.fact_id
    assert claims[0]["evidence"][0]["line_start"] == 2
    assert "policy.limit = 42" in render_document_claim_sheet(db_path=db)
    assert evaluate_document_claims(db_path=db)["grounding_rate"] == 1.0

    stale = mark_document_claims_stale(source_id=str(extraction_id), reason="document replaced", db_path=db)
    assert stale["stale_count"] == 1
    assert list_document_claims(status="expired", db_path=db)[0]["is_stale"] is True


def test_service_hardening_primitives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _isolate_db(tmp_path, monkeypatch)
    from mase.governance.service_hardening import (
        GovernanceWriteQueue,
        backup_database,
        check_rate_limit,
        namespace_key,
        operation_hash,
        record_governance_trace,
        record_idempotency_key,
        restore_database,
    )

    payload_hash = operation_hash({"op": "write", "id": 1})
    accepted = record_idempotency_key("idem-1", payload_hash, result={"ok": True}, db_path=db)
    replayed = record_idempotency_key("idem-1", payload_hash, db_path=db)
    conflict = record_idempotency_key("idem-1", operation_hash({"op": "other"}), db_path=db)
    assert accepted["accepted"] is True
    assert replayed["replayed"] is True
    assert conflict["conflict"] is True

    assert check_rate_limit("tenant-a", limit=1, window_seconds=60, now_epoch=10, db_path=db)["allowed"] is True
    assert check_rate_limit("tenant-a", limit=1, window_seconds=60, now_epoch=11, db_path=db)["allowed"] is False
    assert namespace_key(tenant_id="t", workspace_id="w", visibility="shared") == "t|w|shared"
    assert record_governance_trace("fact.write", scope={"tenant_id": "t"}, db_path=db)["trace_id"].startswith("gt_")
    with GovernanceWriteQueue() as queue:
        assert queue.run(lambda value: value + 1, 1) == 2

    manifest = backup_database(tmp_path / "backups", db_path=db)
    restored = restore_database(manifest["backup_path"], tmp_path / "restore.sqlite3", expected_sha256=manifest["sha256"])
    assert restored["restored"] is True


def test_governance_eval_suite_and_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.eval_suite import GovernanceEvalCase, render_eval_report, run_governance_eval
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="project:eval",
            claim_type="project_fact",
            subject="project",
            predicate="owner",
            object_value="Alice",
            confidence=0.9,
            observed_at="2026-07-04T00:00:00Z",
        ),
        "owner Alice",
        source_type="manual_entry",
        source_id="eval",
        trust_level=5,
        source_full_text="The owner Alice is documented.",
    )
    payload = run_governance_eval(
        [
            GovernanceEvalCase(
                case_id="owner",
                lane="deterministic",
                query="Who owns it?",
                keywords=("owner", "Alice"),
                answer="Alice owns it.",
                expected_verdict="pass",
                expected_terms=("Alice",),
            )
        ]
    )

    assert payload["summary"]["release_gate"] == "passed"
    assert payload["results"][0]["sample_hash"]
    assert "code_hash=" in render_eval_report(payload)
