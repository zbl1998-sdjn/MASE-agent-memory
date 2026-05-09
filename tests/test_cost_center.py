from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase.cost_center import build_cost_center, load_pricing_catalog, resolve_price


def test_pricing_catalog_missing_file_returns_empty(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "missing-pricing.json"
    monkeypatch.setenv("MASE_PRICING_CATALOG_PATH", str(missing))

    catalog = load_pricing_catalog()

    assert catalog["items"] == []
    assert catalog["budget_rules"] == []
    assert catalog["metadata"]["missing_file"] is True
    assert catalog["metadata"]["item_count"] == 0


def test_pricing_catalog_malformed_json_returns_warning(tmp_path: Path, monkeypatch) -> None:
    pricing_path = tmp_path / "pricing.json"
    pricing_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setenv("MASE_PRICING_CATALOG_PATH", str(pricing_path))

    catalog = load_pricing_catalog()

    assert catalog["items"] == []
    assert catalog["metadata"]["missing_file"] is False
    assert catalog["metadata"]["loaded"] is False
    assert catalog["metadata"]["warning_count"] == 1
    assert catalog["metadata"]["warnings"][0].startswith("pricing_catalog_load_failed:")


def test_pricing_catalog_path_can_come_from_config(tmp_path: Path, monkeypatch) -> None:
    pricing_path = tmp_path / "catalog" / "pricing.json"
    pricing_path.parent.mkdir()
    pricing_path.write_text(
        json.dumps({"items": [{"provider": "openai", "model_name": "gpt-config", "cost_per_1k_tokens": 0.03}]}),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"pricing": {"catalog": "catalog/pricing.json"}}), encoding="utf-8")
    monkeypatch.delenv("MASE_PRICING_CATALOG_PATH", raising=False)

    catalog = load_pricing_catalog(config_path)

    assert catalog["metadata"]["source"] == "config.pricing.catalog"
    assert catalog["metadata"]["path"] == str(pricing_path.resolve())
    assert resolve_price("openai", "gpt-config", catalog)["priced"] is True


def test_json_catalog_parses_and_resolves_price(tmp_path: Path, monkeypatch) -> None:
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
                        "currency": "USD",
                        "source": "unit-test",
                        "effective_from": "2026-01-01",
                        "enabled": True,
                    }
                ],
                "budget_rules": [{"name": "warn-demo", "monthly_usd": 10}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MASE_PRICING_CATALOG_PATH", str(pricing_path))

    catalog = load_pricing_catalog()
    price = resolve_price("openai", "gpt-test", catalog)
    summary = build_cost_center(
        [
            {
                "agent_role": "executor",
                "provider": "openai",
                "model_name": "gpt-test",
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200,
                "estimated_cost_usd": 999.0,
            }
        ],
        catalog,
    )

    assert catalog["metadata"]["loaded"] is True
    assert catalog["metadata"]["item_count"] == 1
    assert catalog["budget_rules"][0]["name"] == "warn-demo"
    assert price["priced"] is True
    assert price["pricing_type"] == "catalog"
    assert price["input_cost_per_1k_tokens"] == 0.01
    assert price["output_cost_per_1k_tokens"] == 0.02
    assert summary["totals"]["estimated_cost_usd"] == 0.014
    assert summary["totals"]["ledger_estimated_cost_usd"] == 999.0
    assert summary["pricing_coverage"]["coverage_ratio"] == 1.0


def test_local_provider_cost_is_zero_priced_and_free() -> None:
    price = resolve_price("llama.cpp", "local-model", [])
    summary = build_cost_center(
        [
            {
                "agent_role": "router",
                "provider": "llama.cpp",
                "model_name": "local-model",
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
                "estimated_cost_usd": 0.0,
            }
        ],
        [],
    )

    assert price["status"] == "priced"
    assert price["pricing_type"] == "local"
    assert price["is_free"] is True
    assert summary["totals"]["estimated_cost_usd"] == 0.0
    assert summary["totals"]["cloud_call_count"] == 0
    assert summary["totals"]["local_free_call_count"] == 1
    assert summary["unpriced_call_count"] == 0


def test_unpriced_cloud_call_is_marked_without_defaulting_to_zero() -> None:
    summary = build_cost_center(
        [
            {
                "call_id": "call-unpriced",
                "agent_role": "executor",
                "provider": "openai",
                "model_name": "unknown-model",
                "prompt_tokens": 500,
                "completion_tokens": 100,
                "total_tokens": 600,
                "estimated_cost_usd": 0.0,
            }
        ],
        [],
    )

    event = summary["recent_events"][0]
    assert summary["unpriced_call_count"] == 1
    assert summary["warning_count"] == 1
    assert summary["pricing_coverage"]["unpriced_models"][0]["model_name"] == "unknown-model"
    assert event["pricing_status"] == "unpriced"
    assert event["estimated_cost_usd"] is None
