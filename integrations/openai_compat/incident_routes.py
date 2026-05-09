from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object, scope_from_request
from integrations.openai_compat.runtime import SERVER_CONFIG_PATH, memory_service
from integrations.openai_compat.schemas import SloDashboardRequest
from mase import get_system
from mase.auth_policy import AuthContext
from mase.cost_center import build_cost_center, load_pricing_catalog
from mase.drift_detector import detect_memory_drift
from mase.golden_tests import run_golden_tests
from mase.incidents import build_memory_incidents
from mase.inspector_registry import list_inspectors
from mase.lifecycle import build_lifecycle_report
from mase.slo_dashboard import build_slo_dashboard

router = APIRouter()


def _slo_and_drift(scope: dict[str, Any], cases: list[dict[str, Any]] | None, top_k: int) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = memory_service.list_facts(scope_filters=scope)
    drift = detect_memory_drift(facts)
    golden = run_golden_tests(memory_service, cases, scope=scope, default_top_k=top_k)
    pricing_catalog = load_pricing_catalog(config_path=SERVER_CONFIG_PATH)
    model_calls = get_system(config_path=SERVER_CONFIG_PATH).model_interface.get_call_log()
    cost = build_cost_center(model_calls, pricing_catalog, recent_limit=25)
    lifecycle = build_lifecycle_report(facts)
    slo = build_slo_dashboard(golden_report=golden, lifecycle_report=lifecycle, cost_report=cost)
    return slo, drift


@router.get("/v1/ui/inspectors")
def ui_inspectors(_: AuthContext = Depends(require_permission("read"))) -> dict[str, Any]:
    return response_object("mase.ui.inspectors", list_inspectors(), {"generated_at": int(time.time())})


@router.post("/v1/ui/incidents")
def ui_incidents(
    req: SloDashboardRequest,
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    slo, drift = _slo_and_drift(scope, req.cases, req.top_k)
    data = build_memory_incidents(drift_report=drift, slo_report=slo)
    data["scope"] = scope
    return response_object("mase.ui.incidents", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_incidents", "ui_inspectors"]
