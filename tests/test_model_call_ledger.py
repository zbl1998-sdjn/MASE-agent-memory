from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mase.model_interface import ModelInterface


def _interface(tmp_path: Path) -> ModelInterface:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "models": {
                    "executor": {
                        "provider": "openai",
                        "model_name": "gpt-test",
                        "input_cost_per_1k_tokens": 0.01,
                        "output_cost_per_1k_tokens": 0.02,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return ModelInterface(config_path)


def _interface_with_pricing(tmp_path: Path, catalog: dict) -> ModelInterface:
    pricing_path = tmp_path / "pricing.json"
    pricing_path.write_text(json.dumps(catalog), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "pricing": {"catalog": str(pricing_path)},
                "models": {
                    "executor": {
                        "provider": "openai",
                        "model_name": "gpt-priced",
                        "modes": {
                            "fast": {"model_name": "gpt-missing"},
                        },
                    },
                    "router": {
                        "provider": "llama.cpp",
                        "model_name": "local-router",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return ModelInterface(config_path)


def test_model_call_ledger_normalizes_openai_usage_and_cost(tmp_path: Path) -> None:
    interface = _interface(tmp_path)
    ledger = interface._build_call_ledger(
        agent_type="executor",
        mode="grounded_answer",
        provider="openai",
        model_name="gpt-test",
        elapsed_seconds=0.25,
        request_messages=[{"role": "user", "content": "What is the budget?"}],
        response={
            "message": {"role": "assistant", "content": "3600"},
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200},
        },
        agent_config=interface.get_agent_config("executor"),
        resolved_agent={},
    )

    assert ledger["agent_role"] == "executor"
    assert isinstance(ledger["call_id"], str)
    assert isinstance(ledger["created_at"], str)
    assert ledger["is_local"] is False
    assert ledger["prompt_tokens"] == 1000
    assert ledger["completion_tokens"] == 200
    assert ledger["total_tokens"] == 1200
    assert ledger["estimated_cost_usd"] == 0.014
    assert ledger["token_source"] == "provider_usage"


def test_model_call_ledger_keeps_local_cost_zero_and_estimates_missing_usage(tmp_path: Path) -> None:
    interface = _interface(tmp_path)
    ledger = interface._build_call_ledger(
        agent_type="router",
        mode=None,
        provider="ollama",
        model_name="qwen2.5:7b",
        elapsed_seconds=1.5,
        request_messages=[{"role": "user", "content": "Remember the deployment port."}],
        response={"message": {"role": "assistant", "content": "ok"}},
        agent_config={"provider": "ollama", "model_name": "qwen2.5:7b"},
        resolved_agent={},
    )

    assert ledger["is_local"] is True
    assert ledger["estimated_cost_usd"] == 0.0
    assert ledger["total_tokens"] > 0
    assert ledger["token_source"] == "estimated_chars_div_4"


def test_model_call_ledger_marks_fallback_model(tmp_path: Path) -> None:
    interface = _interface(tmp_path)
    ledger = interface._build_call_ledger(
        agent_type="executor",
        mode="grounded_answer",
        provider="openai",
        model_name="gpt-fallback",
        elapsed_seconds=0.1,
        request_messages=[{"role": "user", "content": "Question"}],
        response={"message": {"role": "assistant", "content": "Answer"}, "usage": {"total_tokens": 8}},
        agent_config=interface.get_agent_config("executor"),
        resolved_agent={},
    )

    assert ledger["fallback_from"] == "openai:gpt-test"
    assert ledger["fallback_to"] == "openai:gpt-fallback"


def test_cost_policy_marks_priced_cloud_and_unpriced_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MASE_ALLOW_CLOUD_MODELS", "1")
    interface = _interface_with_pricing(
        tmp_path,
        {
            "items": [
                {
                    "provider": "openai",
                    "model_name": "gpt-priced",
                    "input_cost_per_1k_tokens": 0.01,
                    "output_cost_per_1k_tokens": 0.02,
                    "source": "unit-test",
                }
            ]
        },
    )

    priced = interface.evaluate_cost_policy("executor")
    unpriced = interface.evaluate_cost_policy("executor", mode="fast")
    routing = interface.describe_cost_routing()

    assert priced["action"] == "allow"
    assert priced["status"] == "ok"
    assert priced["pricing_status"] == "priced"
    assert priced["pricing_source"] == "unit-test"
    assert unpriced["action"] == "allow"
    assert unpriced["status"] == "warn"
    assert "unpriced_cloud_model" in unpriced["warnings"]
    assert routing["summary"]["warning_count"] == 1


def test_cost_policy_blocks_cloud_when_not_explicitly_allowed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MASE_ALLOW_CLOUD_MODELS", raising=False)
    interface = _interface_with_pricing(tmp_path, {"items": []})

    policy = interface.evaluate_cost_policy("executor")

    assert policy["action"] == "blocked"
    assert policy["status"] == "blocked"
    assert "cloud_model_blocked_without_explicit_approval" in policy["warnings"]


def test_call_ledger_includes_cost_policy_fields_for_local_provider(tmp_path: Path) -> None:
    interface = _interface_with_pricing(tmp_path, {"items": []})
    ledger = interface._build_call_ledger(
        agent_type="router",
        mode=None,
        provider="llama.cpp",
        model_name="local-router",
        elapsed_seconds=0.1,
        request_messages=[{"role": "user", "content": "route"}],
        response={"message": {"role": "assistant", "content": "{}"}},
        agent_config=interface.get_agent_config("router"),
        resolved_agent={},
    )

    assert ledger["is_local"] is True
    assert ledger["cost_policy_action"] == "allow"
    assert ledger["cost_policy_status"] == "ok"
    assert ledger["cost_policy_warnings"] == []
