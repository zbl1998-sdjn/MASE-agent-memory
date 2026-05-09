from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from integrations.openai_compat.auth_dependencies import require_permission
from integrations.openai_compat.responses import response_object
from integrations.openai_compat.runtime import SERVER_CONFIG_PATH
from mase import get_system
from mase.auth_policy import AuthContext
from mase.cost_center import build_cost_center, load_pricing_catalog

router = APIRouter()


@router.get("/v1/ui/cost/pricing")
def ui_cost_pricing(_: AuthContext = Depends(require_permission("pricing"))) -> dict[str, Any]:
    pricing_catalog = load_pricing_catalog(config_path=SERVER_CONFIG_PATH)
    metadata = dict(pricing_catalog["metadata"])
    metadata["generated_at"] = int(time.time())
    return response_object(
        "mase.ui.cost.pricing",
        {
            "catalog": pricing_catalog["items"],
            "budget_rules": pricing_catalog["budget_rules"],
            "status": {
                "read_only": True,
                "missing_file": bool(metadata["missing_file"]),
                "unpriced_policy": "warn_only",
                "cloud_calls_default_to_zero": False,
            },
        },
        metadata,
    )


@router.get("/v1/ui/cost/summary")
def ui_cost_summary(
    recent_limit: int = Query(default=50, ge=1, le=200),
    _: AuthContext = Depends(require_permission("pricing")),
) -> dict[str, Any]:
    pricing_catalog = load_pricing_catalog(config_path=SERVER_CONFIG_PATH)
    system = get_system(config_path=SERVER_CONFIG_PATH)
    model_calls = system.model_interface.get_call_log()
    summary = build_cost_center(model_calls, pricing_catalog, recent_limit=recent_limit)
    metadata = dict(pricing_catalog["metadata"])
    metadata["generated_at"] = int(time.time())
    return response_object("mase.ui.cost.summary", summary, metadata)


@router.get("/v1/ui/cost/routing")
def ui_cost_routing(_: AuthContext = Depends(require_permission("pricing"))) -> dict[str, Any]:
    system = get_system(config_path=SERVER_CONFIG_PATH)
    routing = system.model_interface.describe_cost_routing()
    metadata = dict(routing.get("catalog_metadata", {}))
    metadata["generated_at"] = int(time.time())
    return response_object("mase.ui.cost.routing", routing, metadata)
