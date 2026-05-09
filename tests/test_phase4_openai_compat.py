from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from integrations.openai_compat.server import (
    AnswerSupportRequest,
    ConsolidateRequest,
    FactUpsertRequest,
    GoldenTestsRequest,
    MemoryCorrectionRequest,
    MemoryEventRequest,
    MemoryRecallRequest,
    MaseRunRequest,
    ProcedureRequest,
    RepairCaseCreateRequest,
    RepairCaseExecutionRequest,
    RepairCaseTransitionRequest,
    RepairPlanRequest,
    RefusalQualityRequest,
    SessionStateRequest,
    SloDashboardRequest,
    SyntheticReplayRequest,
    WhyNotRememberedRequest,
    app,
    memory_correction,
    MemoryTimelineRequest,
    memory_current_state,
    memory_event,
    memory_explain,
    memory_fact_history,
    memory_fact_upsert,
    memory_facts,
    memory_procedure_register,
    memory_procedures,
    memory_recall,
    memory_session_state_forget,
    memory_session_state_get,
    memory_session_state_upsert,
    memory_snapshot_consolidate,
    memory_snapshots,
    memory_timeline,
    ui_bootstrap,
    ui_audit_events,
    ui_answer_support,
    ui_cost_pricing,
    ui_cost_routing,
    ui_cost_summary,
    ui_golden_tests,
    ui_incidents,
    ui_inspectors,
    ui_lifecycle_report,
    ui_observability,
    ui_privacy_preview,
    ui_privacy_scan,
    ui_quality_report,
    ui_dashboard,
    ui_drift_report,
    ui_repair_case_create,
    ui_repair_case_detail,
    ui_repair_case_diff,
    ui_repair_case_execute,
    ui_repair_case_sandbox,
    ui_repair_case_transition,
    ui_repair_cases,
    ui_repair_plan,
    ui_refusal_quality,
    ui_slo_dashboard,
    ui_synthetic_replay,
    ui_write_inspector,
    ui_why_not_remembered,
)
from mase import MASESystem, MemoryService
from mase.auth_policy import AuthContext


@pytest.fixture()
def openai_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = (tmp_path / "openai-memory.sqlite3").resolve()
    monkeypatch.setenv("MASE_DB_PATH", str(db_path))
    monkeypatch.setenv("MASE_AUDIT_LOG_PATH", str((tmp_path / "audit.jsonl").resolve()))
    return db_path


def _write_minimal_model_config(config_path: Path, model_name: str) -> None:
    config_path.write_text(
        json.dumps(
            {
                "models": {
                    agent: {"provider": "ollama", "model_name": model_name}
                    for agent in ("router", "notetaker", "planner", "executor")
                },
                "memory": {"json_dir": "memory", "log_dir": "logs", "index_db": "memory/index.db"},
            }
        ),
        encoding="utf-8",
    )


def test_openai_memory_endpoints_return_hits(openai_db: Path) -> None:
    del openai_db
    service = MemoryService()
    service.remember_event("oa-thread", "user", "Project codename is Aurora")
    service.upsert_fact("project_status", "codename", "Aurora")

    recall = memory_recall(MemoryRecallRequest(query="Project codename", top_k=3, include_history=True))
    current = memory_current_state(MemoryRecallRequest(query="codename", top_k=3))
    explain = memory_explain(MemoryRecallRequest(query="What is the codename?", top_k=3))
    timeline = memory_timeline(MemoryTimelineRequest(thread_id="oa-thread", limit=10))

    assert recall["data"]
    assert current["data"]
    assert explain["data"]["hits"]
    assert timeline["data"]


def test_openai_memory_endpoints_return_scope_metadata(openai_db: Path) -> None:
    del openai_db
    service = MemoryService()
    scope = {"tenant_id": "tenant-oa", "workspace_id": "ws-api", "visibility": "shared"}
    service.remember_event("oa-thread-scoped", "user", "Scoped codename is Nebula", scope_filters=scope)
    service.upsert_fact("project_status", "codename", "Nebula", scope_filters=scope)

    recall = memory_recall(MemoryRecallRequest(query="codename", top_k=3, include_history=True, **scope))
    explain = memory_explain(MemoryRecallRequest(query="What is the codename?", top_k=3, **scope))
    timeline = memory_timeline(MemoryTimelineRequest(thread_id="oa-thread-scoped", limit=10, **scope))

    assert recall["metadata"]["scope"] == scope
    assert recall["metadata"]["result_count"] >= 1
    assert explain["data"]["scope"] == scope
    assert explain["data"]["metadata"]["hit_count"] >= 1
    assert explain["data"]["hit_inspections"]
    assert explain["data"]["hit_inspections"][0]["rank"] >= 1
    assert "risk_count" in explain["data"]["metadata"]
    assert timeline["metadata"]["scope"] == scope
    assert timeline["data"]


def test_openai_management_endpoints_cover_memory_crud(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-ui", "workspace_id": "ws-console", "visibility": "shared"}

    event = memory_event(
        MemoryEventRequest(
            thread_id="ui-thread",
            role="user",
            content="Console project budget is 3200",
            **scope,
        )
    )
    correction = memory_correction(
        MemoryCorrectionRequest(
            thread_id="ui-thread",
            utterance="Actually console project budget is 3600",
            extra_keywords=["budget"],
            **scope,
        )
    )
    fact = memory_fact_upsert(
        FactUpsertRequest(
            category="finance_budget",
            key="console_budget",
            value="3600",
            source_log_id=correction["data"]["new_log_id"],
            **scope,
        )
    )
    facts = memory_facts(**scope)
    history = memory_fact_history(category="finance_budget", entity_key="console_budget", **scope)
    session = memory_session_state_upsert(
        SessionStateRequest(
            session_id="ui-session",
            context_key="phase",
            context_value="frontend",
            **scope,
        )
    )
    session_rows = memory_session_state_get("ui-session", **scope)
    procedure = memory_procedure_register(
        ProcedureRequest(
            procedure_key="ui-release",
            procedure_type="workflow",
            content="Build frontend before release.",
            **scope,
        )
    )
    procedures = memory_procedures(procedure_type="workflow", **scope)
    snapshot = memory_snapshot_consolidate(ConsolidateRequest(thread_id="ui-thread", **scope))
    snapshots = memory_snapshots(thread_id="ui-thread", **scope)
    forgotten = memory_session_state_forget("ui-session", context_key="phase", **scope)

    assert event["object"] == "mase.memory.event"
    assert fact["data"]["value"] == "3600"
    assert any(row["entity_key"] == "console_budget" for row in facts["data"])
    assert history["object"] == "mase.memory.fact_history"
    assert session["data"]["updated"] is True
    assert session_rows["data"][0]["context_key"] == "phase"
    assert procedure["data"]["updated"] is True
    assert procedures["data"][0]["procedure_key"] == "ui-release"
    assert snapshot["data"]["snapshot_id"] is not None
    assert snapshots["data"]
    assert forgotten["data"]["deleted_count"] == 1


def test_memory_mutation_rejects_missing_internal_api_key(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.setenv("MASE_INTERNAL_API_KEY", "phase-1-key")
    client = TestClient(app)

    response = client.post(
        "/v1/memory/events",
        json={"thread_id": "auth-thread", "role": "user", "content": "unauthorized write"},
    )

    assert response.status_code == 401


def test_memory_mutation_accepts_authorized_internal_api_key(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.setenv("MASE_INTERNAL_API_KEY", "phase-1-key")
    client = TestClient(app)

    response = client.post(
        "/v1/memory/events",
        headers={"Authorization": "Bearer phase-1-key"},
        json={"thread_id": "auth-thread", "role": "user", "content": "authorized write"},
    )

    assert response.status_code == 200
    assert response.json()["object"] == "mase.memory.event"


def test_memory_mutation_rejects_viewer_role(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.setenv("MASE_INTERNAL_API_KEY", "phase-1-key")
    client = TestClient(app)

    response = client.post(
        "/v1/memory/events",
        headers={"Authorization": "Bearer phase-1-key", "x-mase-role": "viewer"},
        json={"thread_id": "auth-thread", "role": "user", "content": "viewer cannot write"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden:write"


def test_pricing_endpoint_requires_pricing_permission(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.setenv("MASE_INTERNAL_API_KEY", "phase-1-key")
    client = TestClient(app)

    viewer_response = client.get(
        "/v1/ui/cost/pricing",
        headers={"Authorization": "Bearer phase-1-key", "x-mase-role": "viewer"},
    )
    auditor_response = client.get(
        "/v1/ui/cost/pricing",
        headers={"Authorization": "Bearer phase-1-key", "x-mase-role": "auditor"},
    )

    assert viewer_response.status_code == 403
    assert viewer_response.json()["detail"] == "forbidden:pricing"
    assert auditor_response.status_code == 200
    assert auditor_response.json()["object"] == "mase.ui.cost.pricing"


def test_multi_user_api_key_mapping_does_not_allow_role_header_escalation(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.delenv("MASE_INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv(
        "MASE_API_KEYS_JSON",
        json.dumps({"viewer-token": {"actor_id": "alice", "role": "viewer"}}),
    )
    client = TestClient(app)

    response = client.get(
        "/v1/ui/cost/pricing",
        headers={"Authorization": "Bearer viewer-token", "x-mase-role": "admin"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden:pricing"


def test_audit_events_record_successful_mutation_and_permission_denial(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.setenv("MASE_INTERNAL_API_KEY", "phase-1-key")
    client = TestClient(app)

    write_response = client.post(
        "/v1/memory/events",
        headers={"Authorization": "Bearer phase-1-key", "x-mase-role": "operator", "x-mase-actor": "ops-user"},
        json={"thread_id": "audit-thread", "role": "user", "content": "audit event content"},
    )
    denied_response = client.get(
        "/v1/ui/cost/pricing",
        headers={"Authorization": "Bearer phase-1-key", "x-mase-role": "viewer", "x-mase-actor": "viewer-user"},
    )
    audit_response = client.get(
        "/v1/ui/audit/events",
        headers={"Authorization": "Bearer phase-1-key", "x-mase-role": "auditor"},
    )

    assert write_response.status_code == 200
    assert denied_response.status_code == 403
    assert audit_response.status_code == 200
    events = audit_response.json()["data"]["events"]
    assert any(event["action"] == "memory.event.create" and event["actor_id"] == "ops-user" for event in events)
    assert any(event["action"] == "auth.permission_denied" and event["outcome"] == "denied" for event in events)


def test_audit_events_function_shape(openai_db: Path) -> None:
    del openai_db

    payload = ui_audit_events(limit=10)

    assert payload["object"] == "mase.ui.audit.events"
    assert isinstance(payload["data"]["events"], list)
    assert "path" in payload["metadata"]


def test_memory_mutation_rejects_read_only_mode(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.setenv("MASE_READ_ONLY", "1")
    client = TestClient(app)

    response = client.post(
        "/v1/memory/events",
        json={"thread_id": "readonly-thread", "role": "user", "content": "blocked write"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "read_only_mode"


def test_trace_logging_rejects_read_only_mode(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.setenv("MASE_READ_ONLY", "true")
    client = TestClient(app)

    response = client.post("/v1/mase/run", json={"query": "dry inspect", "log": True})

    assert response.status_code == 403
    assert response.json()["detail"] == "read_only_mode"


def test_request_body_size_guard_rejects_large_payload(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.setenv("MASE_MAX_REQUEST_BODY_BYTES", "1024")
    client = TestClient(app)

    response = client.post("/v1/memory/recall", json={"query": "x" * 2000, "top_k": 1})

    assert response.status_code == 413


def test_openai_ui_dashboard_returns_product_payload(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-product", "workspace_id": "ws-platform", "visibility": "shared"}
    service = MemoryService()
    service.remember_event("product-thread", "user", "Product cockpit needs visual metrics", scope_filters=scope)
    service.upsert_fact("project_status", "platform_mode", "production", scope_filters=scope)
    service.register_procedure("ship-platform", "Build frontend and run smoke tests.", procedure_type="workflow", scope_filters=scope)
    service.consolidate_session("product-thread", scope_filters=scope)

    bootstrap = ui_bootstrap()
    dashboard = ui_dashboard(**scope)

    assert bootstrap["data"]["product"]["name"] == "MASE Memory Platform"
    assert bootstrap["data"]["product"]["auth_required"] is False
    assert bootstrap["data"]["product"]["read_only"] is False
    assert dashboard["object"] == "mase.ui.dashboard"
    assert dashboard["metadata"]["scope"] == scope
    assert dashboard["data"]["kpis"]["facts"] == 1
    assert dashboard["data"]["kpis"]["events"] >= 1
    assert dashboard["data"]["charts"]["facts_by_category"]
    assert dashboard["data"]["quick_actions"]
    assert dashboard["data"]["system_map"][0]["name"] == "Router"


def test_observability_api_returns_metrics_and_model_ledger(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db

    class FakeModelInterface:
        def get_call_log(self) -> list[dict[str, object]]:
            return [
                {
                    "call_id": "call-1",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "agent_role": "executor",
                    "provider": "openai",
                    "model_name": "gpt-test",
                    "is_local": False,
                    "success": True,
                    "latency_ms": 12.0,
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "token_source": "provider_usage",
                    "estimated_cost_usd": 0.0014,
                }
            ]

    class FakeSystem:
        model_interface = FakeModelInterface()

        def describe_models(self) -> dict[str, dict[str, object]]:
            return {"executor": {"provider": "openai", "model_name": "gpt-test"}}

    monkeypatch.setattr("integrations.openai_compat.observability_routes.get_system", lambda config_path=None: FakeSystem())
    monkeypatch.setattr(
        "integrations.openai_compat.observability_routes.describe_models",
        lambda config_path=None: FakeSystem().describe_models(),
    )

    payload = ui_observability(recent_limit=25)

    assert payload["object"] == "mase.ui.observability"
    ledger = payload["data"]["model_ledger"]
    assert ledger["totals"]["call_count"] == 1
    assert ledger["totals"]["cloud_call_count"] == 1
    assert ledger["totals"]["total_tokens"] == 120
    assert ledger["totals"]["estimated_cost_usd"] == 0.0014
    assert ledger["recent_calls"][0]["call_id"] == "call-1"
    assert payload["data"]["cost_center"]["totals"]["call_count"] == 1


def test_cost_pricing_and_summary_api_shapes(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del openai_db
    pricing_path = tmp_path / "pricing.json"
    pricing_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "provider": "openai",
                        "model_name": "gpt-test",
                        "input_cost_per_1k_tokens": 0.01,
                        "output_cost_per_1k_tokens": 0.02,
                        "source": "unit-test",
                    }
                ],
                "budget_rules": [{"name": "warn-only", "monthly_usd": 10}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MASE_PRICING_CATALOG_PATH", str(pricing_path))

    class FakeModelInterface:
        def get_call_log(self) -> list[dict[str, object]]:
            return [
                {
                    "call_id": "call-priced",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "agent_role": "executor",
                    "provider": "openai",
                    "model_name": "gpt-test",
                    "is_local": False,
                    "prompt_tokens": 1000,
                    "completion_tokens": 200,
                    "total_tokens": 1200,
                    "estimated_cost_usd": 0.0,
                },
                {
                    "call_id": "call-unpriced",
                    "created_at": "2026-01-01T00:00:01+00:00",
                    "agent_role": "planner",
                    "provider": "anthropic",
                    "model_name": "claude-missing",
                    "is_local": False,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "estimated_cost_usd": 0.0,
                },
            ]

    class FakeSystem:
        model_interface = FakeModelInterface()

    monkeypatch.setattr("integrations.openai_compat.cost_routes.get_system", lambda config_path=None: FakeSystem())
    client = TestClient(app)

    pricing_response = client.get("/v1/ui/cost/pricing")
    summary_response = client.get("/v1/ui/cost/summary")

    assert pricing_response.status_code == 200
    pricing_payload = pricing_response.json()
    assert pricing_payload["object"] == "mase.ui.cost.pricing"
    assert pricing_payload["data"]["catalog"][0]["model_name"] == "gpt-test"
    assert pricing_payload["data"]["budget_rules"][0]["name"] == "warn-only"
    assert pricing_payload["data"]["status"]["cloud_calls_default_to_zero"] is False
    assert pricing_payload["metadata"]["missing_file"] is False

    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["object"] == "mase.ui.cost.summary"
    assert summary_payload["data"]["totals"]["call_count"] == 2
    assert summary_payload["data"]["totals"]["estimated_cost_usd"] == 0.014
    assert summary_payload["data"]["unpriced_call_count"] == 1
    assert summary_payload["data"]["pricing_coverage"]["policy"] == "warn_only"
    assert summary_payload["data"]["recent_events"][1]["estimated_cost_usd"] is None


def test_cost_api_functions_return_product_shapes(openai_db: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    del openai_db
    missing = tmp_path / "missing-pricing.json"
    monkeypatch.setenv("MASE_PRICING_CATALOG_PATH", str(missing))

    class FakeModelInterface:
        def get_call_log(self) -> list[dict[str, object]]:
            return []

    class FakeSystem:
        model_interface = FakeModelInterface()

    monkeypatch.setattr("integrations.openai_compat.cost_routes.get_system", lambda config_path=None: FakeSystem())

    pricing = ui_cost_pricing()
    summary = ui_cost_summary(recent_limit=50)

    assert pricing["object"] == "mase.ui.cost.pricing"
    assert pricing["data"]["catalog"] == []
    assert pricing["metadata"]["missing_file"] is True
    assert summary["object"] == "mase.ui.cost.summary"
    assert summary["data"]["pricing_coverage"]["coverage_ratio"] == 1.0


def test_cost_routing_api_shape(openai_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del openai_db

    class FakeModelInterface:
        def describe_cost_routing(self) -> dict[str, object]:
            return {
                "policy": "warn_only_unpriced_cloud",
                "cloud_models_allowed": True,
                "catalog_metadata": {"item_count": 1},
                "summary": {"route_count": 1, "warning_count": 1},
                "routes": [
                    {
                        "agent_type": "executor",
                        "mode": "grounded_answer",
                        "provider": "openai",
                        "model_name": "gpt-missing",
                        "action": "allow",
                        "status": "warn",
                        "warnings": ["unpriced_cloud_model"],
                    }
                ],
            }

    class FakeSystem:
        model_interface = FakeModelInterface()

    monkeypatch.setattr("integrations.openai_compat.cost_routes.get_system", lambda config_path=None: FakeSystem())

    payload = ui_cost_routing()

    assert payload["object"] == "mase.ui.cost.routing"
    assert payload["data"]["summary"]["warning_count"] == 1
    assert payload["data"]["routes"][0]["warnings"] == ["unpriced_cloud_model"]
    assert payload["metadata"]["item_count"] == 1


def test_privacy_scan_and_preview_redact_sensitive_memory(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-privacy", "workspace_id": "ws-privacy"}
    memory_fact_upsert(
        FactUpsertRequest(
            category="contact",
            key="owner_email",
            value="alice@example.com",
            **scope,
        )
    )

    preview = ui_privacy_preview({"authorization": "Bearer secret-secret-secret", "note": "alice@example.com"})
    scan = ui_privacy_scan(limit=100, **scope)

    assert preview["data"]["finding_count"] >= 2
    assert preview["data"]["redacted"]["authorization"] == "[REDACTED]"
    assert preview["data"]["redacted"]["note"] == "[REDACTED:email]"
    assert scan["data"]["summary"]["finding_count"] >= 1
    assert "facts" in scan["data"]["summary"]["sources_with_findings"]


def test_lifecycle_report_surfaces_contract_status(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-life", "workspace_id": "ws-life"}
    memory_fact_upsert(
        FactUpsertRequest(
            category="general_facts",
            key="project_owner",
            value="alice",
            importance_score=0.9,
            **scope,
        )
    )

    report = ui_lifecycle_report(limit=50, **scope)

    assert report["object"] == "mase.ui.lifecycle"
    assert report["data"]["summary"]["fact_count"] == 1
    assert report["data"]["facts"][0]["lifecycle"]["state"] == "long_term_fact"
    assert report["data"]["contract"]["required_fields"] == ["category", "entity_key", "entity_value"]


def test_quality_report_scores_memory_items(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-quality", "workspace_id": "ws-quality"}
    memory_fact_upsert(
        FactUpsertRequest(
            category="general_facts",
            key="quality_owner",
            value="alice",
            source_log_id=123,
            **scope,
        )
    )

    report = ui_quality_report(query="quality owner", limit=50, **scope)

    assert report["object"] == "mase.ui.quality"
    assert report["data"]["summary"]["item_count"] >= 1
    assert 0 <= report["data"]["summary"]["average_score"] <= 1
    assert report["data"]["items"][0]["target_type"] in {"fact", "recall_hit", "trace"}


def test_answer_support_maps_answer_to_memory_evidence(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-answer", "workspace_id": "ws-answer"}
    memory_fact_upsert(
        FactUpsertRequest(
            category="general_facts",
            key="project_owner",
            value="Alice owns the project",
            source_log_id=123,
            **scope,
        )
    )

    report = ui_answer_support(
        AnswerSupportRequest(answer="Alice owns the project.", query="Who owns the project?", **scope)
    )

    assert report["object"] == "mase.ui.answer_support"
    assert report["data"]["summary"]["span_count"] == 1
    assert report["data"]["spans"][0]["support_status"] in {"supported", "weak"}


def test_refusal_quality_flags_over_refusal(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-refusal", "workspace_id": "ws-refusal"}
    memory_fact_upsert(FactUpsertRequest(category="project", key="owner", value="Alice owns the project", **scope))

    report = ui_refusal_quality(
        RefusalQualityRequest(answer="I do not know.", query="Who owns the project?", **scope)
    )

    assert report["object"] == "mase.ui.refusal_quality"
    assert report["data"]["classification"] == "over_refusal"
    assert report["data"]["scope"] == scope


def test_why_not_remembered_diagnoses_recall_path(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-why", "workspace_id": "ws-why"}
    memory_event(MemoryEventRequest(thread_id="why-thread", content="Remember project owner Alice", **scope))

    report = ui_why_not_remembered(WhyNotRememberedRequest(query="project owner", thread_id="why-thread", **scope))

    assert report["object"] == "mase.ui.why_not_remembered"
    assert report["data"]["stages"][0]["stage"] == "event_log"
    assert report["data"]["scope"] == scope


def test_synthetic_replay_runs_scoped_read_only_cases(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-replay", "workspace_id": "ws-replay"}
    memory_fact_upsert(FactUpsertRequest(category="project", key="owner", value="Alice", **scope))

    report = ui_synthetic_replay(
        SyntheticReplayRequest(
            cases=[{"case_id": "owner", "query": "project owner", "expected_terms": ["Alice"]}],
            **scope,
        )
    )

    assert report["object"] == "mase.ui.synthetic_replay"
    assert report["data"]["summary"]["passed_count"] == 1
    assert report["data"]["results"][0]["status"] == "passed"


def test_golden_tests_expose_release_gate(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-golden", "workspace_id": "ws-golden"}
    memory_fact_upsert(FactUpsertRequest(category="project", key="owner", value="Alice", **scope))

    report = ui_golden_tests(
        GoldenTestsRequest(
            cases=[
                {
                    "case_id": "owner",
                    "query": "project owner",
                    "expected_terms": ["Alice"],
                    "severity": "critical",
                }
            ],
            **scope,
        )
    )

    assert report["object"] == "mase.ui.golden_tests"
    assert report["data"]["summary"]["release_gate"] == "passed"


def test_slo_dashboard_aggregates_memory_reliability(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-slo", "workspace_id": "ws-slo"}
    memory_fact_upsert(FactUpsertRequest(category="project", key="owner", value="Alice", **scope))

    report = ui_slo_dashboard(
        SloDashboardRequest(
            cases=[{"case_id": "owner", "query": "project owner", "expected_terms": ["Alice"]}],
            **scope,
        )
    )

    assert report["object"] == "mase.ui.slo_dashboard"
    assert report["data"]["summary"]["objective_count"] >= 4
    assert report["data"]["scope"] == scope


def test_drift_report_surfaces_duplicate_memory(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-drift", "workspace_id": "ws-drift"}
    memory_fact_upsert(FactUpsertRequest(category="project", key="owner", value="Alice", **scope))
    memory_fact_upsert(FactUpsertRequest(category="project", key="lead", value="Alice", **scope))

    report = ui_drift_report(**scope)

    assert report["object"] == "mase.ui.drift"
    assert report["data"]["summary"]["issue_count"] >= 1
    assert report["data"]["scope"] == scope


def test_incidents_and_inspectors_are_exposed(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-incident", "workspace_id": "ws-incident"}
    memory_fact_upsert(FactUpsertRequest(category="project", key="owner", value="Alice", **scope))
    memory_fact_upsert(FactUpsertRequest(category="project", key="owner", value="Bob", **scope))

    inspectors = ui_inspectors()
    incidents = ui_incidents(
        SloDashboardRequest(cases=[{"case_id": "owner", "query": "project owner", "expected_terms": ["Carol"]}], **scope)
    )

    assert inspectors["object"] == "mase.ui.inspectors"
    assert incidents["object"] == "mase.ui.incidents"
    assert incidents["data"]["summary"]["incident_count"] >= 1


def test_write_inspector_links_events_to_current_facts(openai_db: Path) -> None:
    del openai_db
    scope = {"tenant_id": "tenant-write", "workspace_id": "ws-inspector", "visibility": "shared"}
    service = MemoryService()
    correction = service.correct_memory(
        "write-thread",
        "Actually console project budget is 4200",
        extra_keywords=["budget"],
        scope_filters=scope,
    )
    service.upsert_fact(
        "finance_budget",
        "console_budget",
        "4200",
        source_log_id=correction["new_log_id"],
        reason="user_correction",
        scope_filters=scope,
    )

    payload = ui_write_inspector(thread_id="write-thread", limit=10, **scope)

    assert payload["object"] == "mase.ui.write_inspector"
    assert payload["metadata"]["scope"] == scope
    assert payload["data"]["summary"]["linked_fact_count"] == 1
    first_path = payload["data"]["write_paths"][0]
    assert first_path["linked_current_fact_count"] == 1
    assert first_path["linked_current_facts"][0]["entity_key"] == "console_budget"


def test_repair_plan_builds_agent_prompt_with_scope(openai_db: Path) -> None:
    del openai_db
    payload = ui_repair_plan(
        RepairPlanRequest(
            issue_type="recall_failure",
            symptom="The assistant recalled the old budget.",
            evidence={"trace_id": "trace-1"},
            tenant_id="tenant-repair",
            workspace_id="ws-repair",
            visibility="shared",
        )
    )

    assert payload["object"] == "mase.ui.repair_plan"
    assert payload["metadata"]["scope"]["tenant_id"] == "tenant-repair"
    assert "hit_inspections" in " ".join(payload["data"]["recommended_steps"])
    assert "tenant-repair" in payload["data"]["agent_prompt"]


def test_repair_case_api_stores_lifecycle_and_audits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_REPAIR_CASE_PATH", str((tmp_path / "repair_cases.jsonl").resolve()))
    monkeypatch.setenv("MASE_AUDIT_LOG_PATH", str((tmp_path / "audit.jsonl").resolve()))
    auth = AuthContext(
        actor_id="repair-approver-a",
        role="repair_approver",
        permissions=("read", "write", "repair", "repair_approve"),
    )

    created = ui_repair_case_create(
        RepairCaseCreateRequest(
            issue_type="incorrect_memory",
            symptom="wrong project owner remembered",
            evidence={"trace_id": "trace-repair", "authorization": "Bearer secret"},
            tenant_id="tenant-repair",
            workspace_id="ws-repair",
        ),
        auth,
    )
    case_id = created["data"]["case"]["case_id"]

    diagnosed = ui_repair_case_transition(
        case_id,
        RepairCaseTransitionRequest(status="diagnosed", note="fact conflict found"),
        auth,
    )
    diff = ui_repair_case_diff(case_id, auth)
    sandbox = ui_repair_case_sandbox(case_id, auth)
    pending = ui_repair_case_transition(case_id, RepairCaseTransitionRequest(status="pending_approval"), auth)
    approved = ui_repair_case_transition(case_id, RepairCaseTransitionRequest(status="approved"), auth)
    executed = ui_repair_case_execute(
        case_id,
        RepairCaseExecutionRequest(
            confirm=True,
            operations=[
                {
                    "operation": "upsert_fact",
                    "category": "repair",
                    "entity_key": "owner",
                    "entity_value": "alice",
                    "reason": "unit-test",
                }
            ],
            validation_query="Who owns the repaired memory?",
        ),
        auth,
    )
    listed = ui_repair_cases(status="approved", issue_type=None, limit=10, _=auth)
    detail = ui_repair_case_detail(case_id, auth)

    assert diagnosed["data"]["case"]["status"] == "diagnosed"
    assert diff["data"]["diff"]["execution_allowed"] is False
    assert diff["data"]["case"]["diff_proposal"]["proposal_id"] == diff["data"]["diff"]["proposal_id"]
    assert sandbox["data"]["sandbox"]["mutation_count"] == 0
    assert sandbox["data"]["case"]["sandbox_report"]["proposal_id"] == diff["data"]["diff"]["proposal_id"]
    assert pending["data"]["case"]["status"] == "pending_approval"
    assert approved["data"]["case"]["status"] == "approved"
    assert executed["data"]["case"]["status"] == "executed"
    assert executed["data"]["execution"]["mutation_count"] == 1
    assert listed["data"]["summary"]["total_count"] == 0
    assert detail["data"]["case"]["evidence"]["authorization"] == "[REDACTED]"
    audit_events = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "repair_case.create" in audit_events
    assert "repair_case.transition" in audit_events
    assert "repair_case.execute" in audit_events


def test_openai_ui_bootstrap_returns_product_payload_without_mase_config_env(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del openai_db
    monkeypatch.delenv("MASE_CONFIG_PATH", raising=False)

    bootstrap = ui_bootstrap()

    assert bootstrap["object"] == "mase.ui.bootstrap"
    assert bootstrap["data"]["product"]["name"] == "MASE Memory Platform"
    assert os.environ.get("MASE_CONFIG_PATH") is None


def test_openai_ui_bootstrap_uses_server_default_after_temp_config_pollution(
    openai_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del openai_db
    polluted_config = tmp_path / "polluted-config.json"
    _write_minimal_model_config(polluted_config, "polluted-router-model")

    MASESystem(polluted_config)
    monkeypatch.setenv("MASE_CONFIG_PATH", str(polluted_config))

    bootstrap = ui_bootstrap()

    assert bootstrap["data"]["product"]["name"] == "MASE Memory Platform"
    assert bootstrap["data"]["models"]["router"]["model_name"] != "polluted-router-model"


def test_mase_run_request_defaults_to_dry_run() -> None:
    request = MaseRunRequest(query="Inspect without writing memory")

    assert request.log is False
    assert MaseRunRequest(query="Persist this trace", log=True).log is True
