from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .cost_center import resolve_price

_LOCAL_PROVIDERS = {"ollama", "llama_cpp", "llamacpp", "llama.cpp", "local", "localhost"}
_TRUTHY = {"1", "true", "yes", "y", "on"}


def cloud_models_allowed_from_env(environ: Mapping[str, str]) -> bool:
    return str(environ.get("MASE_ALLOW_CLOUD_MODELS") or "").strip().lower() in _TRUTHY


class ModelCallLedgerMixin:
    models_config: dict[str, Any]
    pricing_catalog: dict[str, Any]

    def get_effective_agent_config(self, agent_type: str, mode: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _is_local_provider(provider: str) -> bool:
        return str(provider or "").strip().lower() in _LOCAL_PROVIDERS

    def _evaluate_cost_policy(
        self,
        agent_type: str,
        mode: str | None,
        provider: str,
        model_name: str,
    ) -> dict[str, Any]:
        import os

        price = resolve_price(provider, model_name, self.pricing_catalog)
        warnings: list[str] = []
        action = "allow"
        status = "ok"
        if price.get("is_local"):
            reason = "local_provider_free"
        elif not cloud_models_allowed_from_env(os.environ):
            action = "blocked"
            status = "blocked"
            reason = "cloud_models_disabled"
            warnings.append("cloud_model_blocked_without_explicit_approval")
        elif not price.get("priced"):
            status = "warn"
            reason = str(price.get("reason") or "unpriced_cloud_model")
            warnings.append("unpriced_cloud_model")
        else:
            reason = "priced_cloud_model"
        if price.get("pricing_type") == "partial":
            warnings.append("partial_pricing_catalog_item")
        return {
            "agent_type": agent_type,
            "agent_role": agent_type,
            "mode": mode,
            "provider": provider,
            "model_name": model_name,
            "is_local": bool(price.get("is_local")),
            "action": action,
            "status": status,
            "reason": reason,
            "warnings": warnings,
            "pricing_status": price.get("pricing_status"),
            "pricing_type": price.get("pricing_type"),
            "pricing_source": price.get("source"),
            "currency": price.get("currency"),
            "input_cost_per_1k_tokens": price.get("input_cost_per_1k_tokens"),
            "output_cost_per_1k_tokens": price.get("output_cost_per_1k_tokens"),
            "policy": "warn_only_unpriced_cloud",
        }

    def evaluate_cost_policy(self, agent_type: str, mode: str | None = None) -> dict[str, Any]:
        agent_config = self.get_effective_agent_config(agent_type, mode=mode)
        return self._evaluate_cost_policy(
            agent_type=agent_type,
            mode=mode,
            provider=str(agent_config.get("provider", "ollama")),
            model_name=str(agent_config.get("model_name") or "unknown"),
        )

    def describe_cost_routing(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for agent_type in sorted(self.models_config):
            rows.append(self.evaluate_cost_policy(agent_type))
            modes = self.models_config.get(agent_type, {}).get("modes", {})
            if isinstance(modes, dict):
                for mode in sorted(str(item) for item in modes):
                    rows.append(self.evaluate_cost_policy(agent_type, mode=mode))
        summary = {
            "route_count": len(rows),
            "allowed_count": sum(1 for row in rows if row["action"] == "allow"),
            "blocked_count": sum(1 for row in rows if row["action"] == "blocked"),
            "warning_count": sum(1 for row in rows if row["warnings"]),
            "unpriced_count": sum(1 for row in rows if row["pricing_status"] == "unpriced"),
            "local_free_count": sum(1 for row in rows if row["is_local"]),
        }
        import os

        return {
            "policy": "warn_only_unpriced_cloud",
            "cloud_models_allowed": cloud_models_allowed_from_env(os.environ),
            "catalog_metadata": dict(self.pricing_catalog.get("metadata", {})),
            "summary": summary,
            "routes": rows,
        }

    @staticmethod
    def _numeric(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        normalized = str(text or "")
        if not normalized:
            return 0
        return max(1, round(len(normalized) / 4))

    def _estimate_message_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for message in messages:
            total += self._estimate_text_tokens(str(message.get("role") or ""))
            total += self._estimate_text_tokens(str(message.get("content") or ""))
        return total

    def _response_text(self, response: dict[str, Any]) -> str:
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        return str(content or "")

    def _normalize_token_counts(
        self,
        usage: dict[str, Any] | None,
        *,
        request_messages: list[dict[str, Any]],
        response: dict[str, Any],
    ) -> tuple[int, int, int, str]:
        usage = usage or {}
        prompt = self._numeric(usage.get("prompt_tokens"))
        if prompt is None:
            prompt = self._numeric(usage.get("input_tokens"))
        if prompt is None:
            prompt = self._numeric(usage.get("prompt_eval_count"))
        completion = self._numeric(usage.get("completion_tokens"))
        if completion is None:
            completion = self._numeric(usage.get("output_tokens"))
        if completion is None:
            completion = self._numeric(usage.get("eval_count"))
        total = self._numeric(usage.get("total_tokens"))
        if prompt is not None or completion is not None or total is not None:
            prompt_i = int(prompt or max(0, (total or 0) - (completion or 0)))
            completion_i = int(completion or max(0, (total or 0) - prompt_i))
            total_i = int(total or prompt_i + completion_i)
            return prompt_i, completion_i, total_i, "provider_usage"
        prompt_i = self._estimate_message_tokens(request_messages)
        completion_i = self._estimate_text_tokens(self._response_text(response))
        return prompt_i, completion_i, prompt_i + completion_i, "estimated_chars_div_4"

    def _resolve_token_pricing(
        self,
        *,
        agent_config: dict[str, Any],
        resolved_agent: dict[str, Any],
        provider: str,
    ) -> tuple[float, float, float]:
        if self._is_local_provider(provider):
            return 0.0, 0.0, 0.0
        config = dict(agent_config)
        config.update({key: value for key, value in resolved_agent.items() if value is not None})
        flat = float(config.get("cost_per_1k_tokens") or 0.0)
        input_cost = float(config.get("input_cost_per_1k_tokens") or config.get("prompt_cost_per_1k_tokens") or flat)
        output_cost = float(config.get("output_cost_per_1k_tokens") or config.get("completion_cost_per_1k_tokens") or flat)
        return input_cost, output_cost, flat

    def _build_call_ledger(
        self,
        *,
        agent_type: str,
        mode: str | None,
        provider: str,
        model_name: str,
        elapsed_seconds: float,
        request_messages: list[dict[str, Any]],
        response: dict[str, Any],
        agent_config: dict[str, Any],
        resolved_agent: dict[str, Any],
    ) -> dict[str, Any]:
        usage = self._extract_usage(provider, response)
        prompt_tokens, completion_tokens, total_tokens, token_source = self._normalize_token_counts(
            usage,
            request_messages=request_messages,
            response=response,
        )
        input_cost, output_cost, flat_cost = self._resolve_token_pricing(
            agent_config=agent_config,
            resolved_agent=resolved_agent,
            provider=provider,
        )
        estimated_cost = 0.0
        if not self._is_local_provider(provider):
            estimated_cost = (prompt_tokens / 1000.0 * input_cost) + (completion_tokens / 1000.0 * output_cost)
        configured_provider = str(agent_config.get("provider") or provider)
        configured_model = str(agent_config.get("model_name") or model_name)
        fallback_from = resolved_agent.get("fallback_from")
        fallback_to = resolved_agent.get("fallback_to")
        if fallback_from is None and (configured_provider, configured_model) != (provider, model_name):
            fallback_from = f"{configured_provider}:{configured_model}"
            fallback_to = f"{provider}:{model_name}"
        cost_policy = self._evaluate_cost_policy(agent_type, mode, provider, model_name)
        return {
            "call_id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "agent_type": agent_type,
            "agent_role": agent_type,
            "mode": mode,
            "provider": provider,
            "model_name": model_name,
            "is_local": self._is_local_provider(provider),
            "success": True,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "latency_ms": round(elapsed_seconds * 1000.0, 3),
            "usage": usage,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "token_source": token_source,
            "input_cost_per_1k_tokens": input_cost,
            "output_cost_per_1k_tokens": output_cost,
            "cost_per_1k_tokens": flat_cost,
            "estimated_cost_usd": round(estimated_cost, 8),
            "fallback_from": fallback_from,
            "fallback_to": fallback_to,
            "cost_policy_action": cost_policy["action"],
            "cost_policy_status": cost_policy["status"],
            "cost_policy_warnings": cost_policy["warnings"],
        }

    def _extract_usage(self, provider: str, response: dict[str, Any]) -> dict[str, Any] | None:
        usage = response.get("usage")
        if isinstance(usage, dict):
            return dict(usage)
        if provider == "ollama":
            usage_fields = {
                "prompt_eval_count": response.get("prompt_eval_count"),
                "eval_count": response.get("eval_count"),
                "total_duration": response.get("total_duration"),
                "load_duration": response.get("load_duration"),
                "prompt_eval_duration": response.get("prompt_eval_duration"),
                "eval_duration": response.get("eval_duration"),
            }
            filtered = {key: value for key, value in usage_fields.items() if value is not None}
            return filtered or None
        return None
