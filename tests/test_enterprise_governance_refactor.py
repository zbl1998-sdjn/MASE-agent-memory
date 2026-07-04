from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest


def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "enterprise.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    return db


def test_fact_state_machine_rejects_invalid_edges() -> None:
    from mase.core import FactStateMachine, FactTransition, InvalidFactTransition

    machine = FactStateMachine()
    assert machine.can_transition("quarantined", "active")
    machine.validate(
        FactTransition(
            fact_id="fact_1",
            from_status="quarantined",
            to_status="active",
            reason_code="human_approve",
        )
    )
    with pytest.raises(InvalidFactTransition):
        machine.validate(
            FactTransition(
                fact_id="fact_1",
                from_status="rejected",
                to_status="active",
                reason_code="bad",
            )
        )


def test_enterprise_mode_dual_writes_notetaker_fact_candidate_and_active_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_ENTERPRISE_MODE", "1")
    from mase.governance.write_facade import GovernedFactWriteFacade
    from mase_tools.memory.api import mase2_upsert_fact, mase2_write_interaction

    log_result = mase2_write_interaction("thread-a", "user", "Project owner is Alice.")
    source_log_id = int(log_result.rsplit(" ", 1)[-1])
    message = mase2_upsert_fact(
        "project_status",
        "owner",
        "Alice",
        reason="notetaker",
        source_log_id=source_log_id,
    )

    assert "governance_candidate=" in message
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    candidate = conn.execute("SELECT * FROM governance_fact_candidates").fetchone()
    fact = conn.execute("SELECT * FROM facts").fetchone()
    span = conn.execute("SELECT * FROM evidence_spans").fetchone()
    conn.close()
    assert candidate["category"] == "project_status"
    assert candidate["fact_status"] == "active"
    assert fact["status"] == "active"
    assert fact["subject"] == "project_status"
    assert span["span_start"] is not None

    diff = GovernedFactWriteFacade().shadow_read_diff(category="project_status", key="owner")
    assert diff["legacy_count"] == 1
    assert diff["diff_count"] == 0


def test_enterprise_dual_write_without_source_is_quarantined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_GOVERNANCE_DUAL_WRITE", "1")
    from mase_tools.memory.api import mase2_upsert_fact

    mase2_upsert_fact("project_status", "owner", "Mallory", reason="model inference")

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    fact = conn.execute("SELECT * FROM facts").fetchone()
    candidate = conn.execute("SELECT * FROM governance_fact_candidates").fetchone()
    conn.close()
    assert candidate["status"] == "proposed"
    assert fact["claim_type"] == "inference"
    assert fact["status"] == "quarantined"


def test_semantic_claim_verifier_detects_paraphrase_and_contradiction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.evidence_pack import compile_evidence_pack
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact
    from mase.governance.semantic_claim_verifier import verify_semantic_claims

    propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="project:enterprise",
            claim_type="project_fact",
            subject="project",
            predicate="owner",
            object_value="Alice",
            confidence=0.9,
            observed_at="2026-07-04T00:00:00Z",
        ),
        "owner is Alice",
        source_type="manual_entry",
        source_id="semantic-test",
        trust_level=5,
        source_full_text="The project owner is Alice.",
    )
    pack = compile_evidence_pack("Who owns the project?", ["owner", "Alice"])

    supported = verify_semantic_claims("Alice owns the project.", pack)
    contradicted = verify_semantic_claims("Bob owns the project.", pack)

    assert supported["verdict"] == "pass"
    assert supported["judgments"][0]["status"] == "supported"
    assert contradicted["verdict"] == "refuse"
    assert contradicted["judgments"][0]["status"] == "contradicted"
