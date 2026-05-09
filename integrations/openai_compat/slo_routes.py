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
from mase.golden_tests import run_golden_tests
from mase.lifecycle import build_lifecycle_report
from mase.slo_dashboard import build_slo_dashboard

router = APIRouter()


@router.post("/v1/ui/slo-dashboard")
def ui_slo_dashboard(
    req: SloDashboardRequest,
    _: AuthContext = Depends(require_permission("read")),
) -> dict[str, Any]:
    scope = scope_from_request(req)
    facts = memory_service.list_facts(scope_filters=scope)
    golden = run_golden_tests(memory_service, req.cases, scope=scope, default_top_k=req.top_k)
    lifecycle = build_lifecycle_report(facts)
    pricing_catalog = load_pricing_catalog(config_path=SERVER_CONFIG_PATH)
    model_calls = get_system(config_path=SERVER_CONFIG_PATH).model_interface.get_call_log()
    cost = build_cost_center(model_calls, pricing_catalog, recent_limit=25)
    data = build_slo_dashboard(golden_report=golden, lifecycle_report=lifecycle, cost_report=cost)
    data["scope"] = scope
    return response_object("mase.ui.slo_dashboard", data, {"scope": scope, "generated_at": int(time.time())})


__all__ = ["router", "ui_slo_dashboard"]
