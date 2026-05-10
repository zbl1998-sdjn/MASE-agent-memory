# NOTE: BASE_DIR below was auto-patched during src/ migration so that
# Path(__file__).parents[2] continues to resolve to the project root.
from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

import httpx
import ollama

from .cost_center import load_pricing_catalog, resolve_price
from .health_tracker import get_tracker

BASE_DIR = Path(__file__).resolve().parents[2]
_LOCAL_PROVIDERS = {"ollama", "llama_cpp", "llamacpp", "llama.cpp", "local", "localhost"}
_TRUTHY = {"1", "true", "yes", "y", "on"}


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    if config_path:
        return Path(config_path).resolve()
    env = os.environ.get("MASE_CONFIG_PATH")
    if env:
        return Path(env).resolve()
    # Search candidates in priority order so `pip install -e .` and
    # `pip install mase-demo` both work without requiring users to set
    # MASE_CONFIG_PATH manually.
    candidates = [
        Path.cwd() / "config.json",
        BASE_DIR / "config.json",                    # source-tree layout
        Path(__file__).resolve().parent / "config.json",  # bundled fallback (post-install)
        Path.home() / ".mase" / "config.json",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    # Last resort: return the source-tree default so error messages stay informative.
    return (BASE_DIR / "config.json").resolve()


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = resolve_config_path(config_path)
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == "MASE_CONFIG_PATH":
            continue
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_relative_path(raw_path: str | Path, base_dir: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def resolve_runs_dir() -> Path | None:
    raw = os.environ.get("MASE_RUNS_DIR")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def cloud_models_allowed() -> bool:
    return str(os.environ.get("MASE_ALLOW_CLOUD_MODELS") or "").strip().lower() in _TRUTHY


def _enforce_cloud_model_policy(provider: str, agent_type: str, mode: str | None, model_name: str) -> None:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider in _LOCAL_PROVIDERS or cloud_models_allowed():
        return
    mode_label = mode or "<default>"
    raise RuntimeError(
        "Cloud model call blocked by policy. "
        "Set MASE_ALLOW_CLOUD_MODELS=1 only after explicit user approval. "
        f"Blocked provider={provider}, model={model_name}, agent={agent_type}, mode={mode_label}."
    )


def load_memory_settings(config_path: str | Path | None = None) -> dict[str, Path]:
    path = resolve_config_path(config_path)
    config = load_config(path)
    memory_config = config.get("memory", {})
    runs_dir = resolve_runs_dir()

    raw_json_dir = memory_config.get("json_dir", "memory")
    if runs_dir is not None and str(raw_json_dir).strip().replace("\\", "/") in {"", "memory"}:
        json_dir = runs_dir / "memory"
    else:
        json_dir = _resolve_relative_path(raw_json_dir, path.parent)
    log_dir_raw = Path(memory_config.get("log_dir", "logs"))
    log_dir = log_dir_raw.resolve() if log_dir_raw.is_absolute() else (json_dir / log_dir_raw).resolve()
    raw_index_db = memory_config.get("index_db", "memory/index.db")
    if runs_dir is not None and str(raw_index_db).strip().replace("\\", "/") in {"", "memory/index.db"}:
        index_db = runs_dir / "memory" / "index.db"
    else:
        index_db = _resolve_relative_path(raw_index_db, path.parent)

    return {
        "json_dir": json_dir,
        "log_dir": log_dir,
        "index_db": index_db,
    }


class ModelInterface:
    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = resolve_config_path(config_path)
        self.call_log: list[dict[str, Any]] = []
        self._http_clients: dict[str, httpx.Client] = {}
        self.reload()

    def reload(self) -> None:
        self._close_http_clients()
        self.config = load_config(self.config_path)
        self.models_config = self.config.get("models", {})
        self.fallbacks = self.config.get("fallbacks", {})
        self.pricing_catalog = load_pricing_catalog(config_path=self.config_path)
        env_file = self.config.get("env_file")
        if env_file:
            _load_env_file(_resolve_relative_path(env_file, self.config_path.parent))

    def _close_http_clients(self) -> None:
        for client in self._http_clients.values():
            client.close()
        self._http_clients = {}

    def __del__(self) -> None:
        self._close_http_clients()

    def reset_call_log(self) -> None:
        self.call_log = []

    def get_call_log(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.call_log]

    @staticmethod
    def _is_local_provider(provider: str) -> bool:
        return str(provider or "").strip().lower() in _LOCAL_PROVIDERS

    def get_agent_config(self, agent_type: str) -> dict[str, Any]:
        if agent_type not in self.models_config:
            raise KeyError(f"配置中不存在智能体: {agent_type}")
        return self.models_config[agent_type]

    def _merge_config_override(self, base_config: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        for key, value in override.items():
            if key == "extends":
                continue
            if key in {"headers", "query_params", "extra_body"}:
                merged = dict(base_config.get(key, {}))
                merged.update(value or {})
                base_config[key] = merged
            else:
                base_config[key] = deepcopy(value)
        return base_config

    def get_effective_agent_config(self, agent_type: str, mode: str | None = None) -> dict[str, Any]:
        agent_config = deepcopy(self.get_agent_config(agent_type))
        if not mode:
            return agent_config

        modes = agent_config.get("modes", {})
        mode_config = deepcopy(modes.get(mode, {}))
        parent_mode = str(mode_config.get("extends") or "").strip()
        if parent_mode:
            parent_config = deepcopy(modes.get(parent_mode, {}))
            agent_config = self._merge_config_override(agent_config, parent_config)
        agent_config = self._merge_config_override(agent_config, mode_config)
        return agent_config

    def describe_agent(self, agent_type: str, mode: str | None = None) -> dict[str, Any]:
        agent_config = self.get_effective_agent_config(agent_type, mode=mode)
        return {
            "mode": mode,
            "provider": agent_config.get("provider"),
            "model_name": agent_config.get("model_name"),
            "temperature": agent_config.get("temperature"),
            "max_tokens": agent_config.get("max_tokens"),
            "base_url": agent_config.get("base_url"),
        }

    def describe_executor_mode(self, mode: str) -> dict[str, Any]:
        return self.describe_agent("executor", mode=mode)

    def _evaluate_cost_policy(
        self,
        agent_type: str,
        mode: str | None,
        provider: str,
        model_name: str,
    ) -> dict[str, Any]:
        price = resolve_price(provider, model_name, self.pricing_catalog)
        warnings: list[str] = []
        action = "allow"
        status = "ok"
        if price.get("is_local"):
            reason = "local_provider_free"
        elif not cloud_models_allowed():
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
        return {
            "policy": "warn_only_unpriced_cloud",
            "cloud_models_allowed": cloud_models_allowed(),
            "catalog_metadata": dict(self.pricing_catalog.get("metadata", {})),
            "summary": summary,
            "routes": rows,
        }

    def get_system_prompt(
        self,
        agent_type: str,
        mode: str | None = None,
        prompt_key: str = "system_prompt",
    ) -> str | None:
        agent_config = self.get_effective_agent_config(agent_type, mode=mode)
        return agent_config.get(prompt_key)

    def inject_system_prompt(self, messages: list[dict[str, Any]], system_prompt: str) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        has_system = False
        for message in messages:
            if message.get("role") == "system":
                prepared.append({**message, "content": system_prompt})
                has_system = True
            else:
                prepared.append(dict(message))
        if not has_system:
            prepared.insert(0, {"role": "system", "content": system_prompt})
        return prepared

    def chat(
        self,
        agent_type: str,
        messages: list[dict[str, Any]],
        mode: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        override_system_prompt: str | None = None,
        prompt_key: str = "system_prompt",
    ) -> dict[str, Any]:
        agent_config = self.get_effective_agent_config(agent_type, mode=mode)
        provider = agent_config.get("provider", "ollama")
        model_name = agent_config["model_name"]
        _enforce_cloud_model_policy(str(provider), agent_type, mode, str(model_name))
        temperature = agent_config.get("temperature", 0.7)
        max_tokens = agent_config.get("max_tokens", 512)
        # MC self-consistency hook: env override applies only when explicitly set.
        # Only affects the executor agent to avoid perturbing router/notetaker.
        _temp_env = os.environ.get("MASE_TEMP_OVERRIDE")
        if _temp_env and agent_type == "executor":
            try:
                temperature = float(_temp_env)
            except (TypeError, ValueError):
                pass

        system_prompt = override_system_prompt or self.get_system_prompt(
            agent_type=agent_type,
            mode=mode,
            prompt_key=prompt_key,
        )
        prepared_messages = (
            self.inject_system_prompt(messages, system_prompt)
            if system_prompt
            else [dict(message) for message in messages]
        )
        started = time.perf_counter()
        if provider == "ollama":
            response = self._call_ollama(
                agent_config=agent_config,
                model=model_name,
                messages=prepared_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )
        elif provider == "anthropic":
            response = self._call_anthropic(
                agent_config=agent_config,
                model=model_name,
                messages=prepared_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )
        elif provider == "llama_cpp":
            response = self._call_llama_cpp(model_name, prepared_messages, temperature, max_tokens)
        elif provider == "openai":
            response = self._call_openai(
                agent_config=agent_config,
                model=model_name,
                messages=prepared_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        resolved_agent = response.get("resolved_agent") or {}
        elapsed_seconds = time.perf_counter() - started
        self.call_log.append(
            self._build_call_ledger(
                agent_type=agent_type,
                mode=mode,
                provider=str(resolved_agent.get("provider", provider)),
                model_name=str(resolved_agent.get("model_name", model_name)),
                elapsed_seconds=elapsed_seconds,
                request_messages=prepared_messages,
                response=response,
                agent_config=agent_config,
                resolved_agent=resolved_agent,
            )
        )
        return response

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
            "created_at": datetime.now(UTC).isoformat(),
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

    def _split_system_messages(self, messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        conversational: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "")
            content = message.get("content")
            normalized_content = content if isinstance(content, str) else str(content or "")
            if role == "system":
                if normalized_content.strip():
                    system_parts.append(normalized_content)
                continue
            conversational.append(
                {
                    "role": role or "user",
                    "content": normalized_content,
                }
            )
        system_prompt = "\n\n".join(part for part in system_parts if part.strip()) or None
        return system_prompt, conversational

    def _is_transient_ollama_error(self, error: Exception) -> bool:
        message = str(error)
        markers = [
            "ConnectionError",
            "ConnectError",
            "Failed to connect to Ollama",
            "10054",
            "10061",
            "Connection reset",
            "Connection refused",
            "actively refused",
            "远程主机强迫关闭了一个现有的连接",
            "由于目标计算机积极拒绝，无法连接",
            "Server disconnected",
            "Connection aborted",
            "timed out",
            "timeout",
            "RemoteProtocolError",
            "Temporary failure",
        ]
        return any(marker in message for marker in markers)

    def _is_transient_openai_error(self, error: Exception) -> bool:
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in {408, 409, 429, 500, 502, 503, 504}
        return isinstance(error, httpx.TimeoutException | httpx.NetworkError | httpx.RemoteProtocolError)

    def _call_ollama(
        self,
        agent_config: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        retry_count = max(1, int(self.fallbacks.get("ollama_retry_count", 6)))
        retry_delay = float(self.fallbacks.get("ollama_retry_delay", 3))
        last_error: Exception | None = None

        for attempt in range(1, retry_count + 1):
            try:
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                        **agent_config.get("ollama_options", {}),
                    },
                    **agent_config.get("extra_body", {}),
                }
                keep_alive = self._resolve_ollama_keep_alive(agent_config)
                if keep_alive is not None:
                    payload["keep_alive"] = keep_alive
                if tools is not None:
                    payload["tools"] = tools
                return ollama.chat(**payload)
            except (httpx.HTTPError, OSError) as error:
                last_error = error
                if attempt >= retry_count or not self._is_transient_ollama_error(error):
                    raise
                if bool(self.fallbacks.get("ollama_wait_for_healthy", True)):
                    self._wait_for_ollama_ready()
                time.sleep(retry_delay * attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("模型调用失败，未返回结果。")

    def _resolve_ollama_keep_alive(self, agent_config: dict[str, Any]) -> str | int | float | None:
        raw_value = os.environ.get("MASE_OLLAMA_KEEP_ALIVE")
        if raw_value is None or not str(raw_value).strip():
            raw_value = agent_config.get("keep_alive", self.fallbacks.get("ollama_keep_alive"))
        if raw_value is None:
            return None
        if isinstance(raw_value, int | float):
            return raw_value
        text = str(raw_value).strip()
        if not text:
            return None
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?\d+\.\d+", text):
            return float(text)
        return text

    def _resolve_ollama_base_url(self) -> str:
        raw_host = str(
            self.fallbacks.get("ollama_base_url")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        ).strip()
        if not raw_host.startswith(("http://", "https://")):
            raw_host = f"http://{raw_host}"
        return raw_host.rstrip("/")

    def _probe_ollama_ready(self, timeout_seconds: float) -> bool:
        endpoint = f"{self._resolve_ollama_base_url()}/api/tags"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(endpoint)
                response.raise_for_status()
            return True
        except (httpx.HTTPError, OSError):
            return False

    def _wait_for_ollama_ready(self) -> bool:
        timeout_seconds = float(self.fallbacks.get("ollama_healthcheck_timeout", 20))
        poll_interval = float(self.fallbacks.get("ollama_healthcheck_poll_interval", 1.5))
        probe_timeout = float(self.fallbacks.get("ollama_healthcheck_probe_timeout", 3))
        deadline = time.perf_counter() + max(0.0, timeout_seconds)
        while time.perf_counter() <= deadline:
            if self._probe_ollama_ready(timeout_seconds=probe_timeout):
                return True
            time.sleep(max(0.1, poll_interval))
        return False

    def _resolve_http_timeout_settings(self, agent_config: dict[str, Any]) -> dict[str, float]:
        timeout_config = agent_config.get("timeout")
        config = timeout_config if isinstance(timeout_config, dict) else {}
        overall = float(
            config.get(
                "overall",
                agent_config.get("timeout_seconds", agent_config.get("overall_timeout_seconds", self.fallbacks.get("cloud_timeout_seconds", 60))),
            )
        )
        connect = float(
            config.get(
                "connect",
                agent_config.get(
                    "connect_timeout_seconds",
                    self.fallbacks.get("cloud_connect_timeout_seconds", min(overall, 10)),
                ),
            )
        )
        read = float(
            config.get(
                "read",
                agent_config.get("read_timeout_seconds", self.fallbacks.get("cloud_read_timeout_seconds", overall)),
            )
        )
        write = float(
            config.get(
                "write",
                agent_config.get("write_timeout_seconds", self.fallbacks.get("cloud_write_timeout_seconds", min(read, 30))),
            )
        )
        pool = float(
            config.get(
                "pool",
                agent_config.get("pool_timeout_seconds", self.fallbacks.get("cloud_pool_timeout_seconds", min(connect + 2, 15))),
            )
        )
        return {
            "overall": max(0.1, overall),
            "connect": max(0.1, connect),
            "read": max(0.1, read),
            "write": max(0.1, write),
            "pool": max(0.1, pool),
        }

    def _resolve_http_limits_settings(self, agent_config: dict[str, Any]) -> dict[str, float]:
        limits_config = agent_config.get("pool_limits")
        config = limits_config if isinstance(limits_config, dict) else {}
        max_connections = int(
            config.get(
                "max_connections",
                agent_config.get("max_connections", self.fallbacks.get("cloud_max_connections", 24)),
            )
        )
        max_keepalive_connections = int(
            config.get(
                "max_keepalive_connections",
                agent_config.get(
                    "max_keepalive_connections",
                    self.fallbacks.get("cloud_max_keepalive_connections", min(max_connections, 12)),
                ),
            )
        )
        keepalive_expiry = float(
            config.get(
                "keepalive_expiry",
                agent_config.get("keepalive_expiry_seconds", self.fallbacks.get("cloud_keepalive_expiry_seconds", 30)),
            )
        )
        return {
            "max_connections": max(1, max_connections),
            "max_keepalive_connections": max(1, max_keepalive_connections),
            "keepalive_expiry": max(1.0, keepalive_expiry),
        }

    def _get_http_client(self, agent_config: dict[str, Any]) -> httpx.Client:
        timeout_settings = self._resolve_http_timeout_settings(agent_config)
        limits_settings = self._resolve_http_limits_settings(agent_config)
        http2 = bool(agent_config.get("http2", self.fallbacks.get("cloud_http2", False)))
        client_key = json.dumps(
            {
                "timeout": timeout_settings,
                "limits": limits_settings,
                "http2": http2,
            },
            sort_keys=True,
        )
        client = self._http_clients.get(client_key)
        if client is None:
            client = httpx.Client(
                timeout=httpx.Timeout(
                    timeout=timeout_settings["overall"],
                    connect=timeout_settings["connect"],
                    read=timeout_settings["read"],
                    write=timeout_settings["write"],
                    pool=timeout_settings["pool"],
                ),
                limits=httpx.Limits(
                    max_connections=int(limits_settings["max_connections"]),
                    max_keepalive_connections=int(limits_settings["max_keepalive_connections"]),
                    keepalive_expiry=float(limits_settings["keepalive_expiry"]),
                ),
                http2=http2,
            )
            self._http_clients[client_key] = client
        return client

    def _resolve_http_retry_settings(self, agent_config: dict[str, Any]) -> dict[str, float]:
        retry_count = int(agent_config.get("retry_count", self.fallbacks.get("cloud_retry_count", self.fallbacks.get("openai_retry_count", 3))))
        retry_base_delay = float(
            agent_config.get(
                "retry_base_delay",
                agent_config.get("retry_delay", self.fallbacks.get("cloud_retry_base_delay", self.fallbacks.get("openai_retry_delay", 2))),
            )
        )
        retry_max_delay = float(agent_config.get("retry_max_delay", self.fallbacks.get("cloud_retry_max_delay", max(retry_base_delay, 8.0))))
        retry_jitter = float(agent_config.get("retry_jitter", self.fallbacks.get("cloud_retry_jitter", 0.4)))
        retry_backoff_multiplier = float(
            agent_config.get("retry_backoff_multiplier", self.fallbacks.get("cloud_retry_backoff_multiplier", 2.0))
        )
        return {
            "retry_count": max(1, retry_count),
            "retry_base_delay": max(0.0, retry_base_delay),
            "retry_max_delay": max(0.0, retry_max_delay),
            "retry_jitter": max(0.0, retry_jitter),
            "retry_backoff_multiplier": max(1.0, retry_backoff_multiplier),
        }

    def _compute_retry_delay(self, attempt: int, retry_settings: dict[str, float]) -> float:
        base_delay = retry_settings["retry_base_delay"] * (
            retry_settings["retry_backoff_multiplier"] ** max(0, attempt - 1)
        )
        capped_delay = min(base_delay, retry_settings["retry_max_delay"])
        jitter = random.uniform(0.0, retry_settings["retry_jitter"])
        return max(0.0, capped_delay + jitter)

    def _iter_model_candidates(self, agent_config: dict[str, Any], primary_model: str) -> list[dict[str, Any]]:
        primary_config = deepcopy(agent_config)
        primary_config["model_name"] = primary_model
        primary_config.pop("fallback_models", None)
        candidates = [primary_config]
        for fallback in agent_config.get("fallback_models") or []:
            candidate = deepcopy(primary_config)
            if isinstance(fallback, str):
                candidate["model_name"] = fallback
            elif isinstance(fallback, dict):
                candidate = self._merge_config_override(candidate, fallback)
            else:
                continue
            candidate.pop("fallback_models", None)
            candidates.append(candidate)
        # Optionally append a local fallback as ultimate safety-net.
        local_fallback = self.fallbacks.get("local_fallback")
        if isinstance(local_fallback, dict) and local_fallback.get("model_name") and local_fallback.get("provider"):
            already_present = any(
                str(c.get("provider")) == str(local_fallback.get("provider"))
                and str(c.get("model_name")) == str(local_fallback.get("model_name"))
                for c in candidates
            )
            if not already_present:
                candidates.append(self._merge_config_override(deepcopy(primary_config), local_fallback))
        # Health-aware re-ordering. Single candidate stays as-is.
        if len(candidates) > 1:
            try:
                candidates = get_tracker().sort_candidates(candidates)
            except Exception:
                pass
        return candidates

    def _attach_resolved_agent(
        self,
        response: dict[str, Any],
        agent_config: dict[str, Any],
        model_name: str,
        endpoint: str,
    ) -> dict[str, Any]:
        response["resolved_agent"] = {
            "provider": agent_config.get("provider"),
            "model_name": model_name,
            "base_url": agent_config.get("base_url"),
            "endpoint": endpoint,
            "cost_per_1k_tokens": agent_config.get("cost_per_1k_tokens"),
            "input_cost_per_1k_tokens": agent_config.get("input_cost_per_1k_tokens"),
            "output_cost_per_1k_tokens": agent_config.get("output_cost_per_1k_tokens"),
        }
        return response

    def _call_llama_cpp(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"provider=llama_cpp 已预留接口，但当前尚未接入。model={model}, max_tokens={max_tokens}, temperature={temperature}"
        )

    def _call_openai(
        self,
        agent_config: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        tracker = get_tracker()
        for candidate_config in self._iter_model_candidates(agent_config, primary_model=model):
            candidate_model = str(candidate_config.get("model_name") or model)
            candidate_provider = str(candidate_config.get("provider") or "openai")
            endpoint = self._resolve_openai_endpoint(candidate_config)
            api_key = self._resolve_api_key(candidate_config)
            auth_header = candidate_config.get("auth_header", "Authorization")
            auth_scheme = candidate_config.get("auth_scheme", "Bearer")
            headers = {
                "Content-Type": "application/json",
                **candidate_config.get("headers", {}),
            }
            if api_key:
                headers[auth_header] = f"{auth_scheme} {api_key}".strip() if auth_scheme else api_key

            payload: dict[str, Any] = {
                "model": candidate_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **candidate_config.get("extra_body", {}),
            }
            if tools is not None:
                payload["tools"] = tools
                payload.setdefault("tool_choice", "auto")

            query_params = candidate_config.get("query_params") or {}
            retry_settings = self._resolve_http_retry_settings(candidate_config)
            client = self._get_http_client(candidate_config)

            for attempt in range(1, int(retry_settings["retry_count"]) + 1):
                start_t = time.time()
                try:
                    response = client.post(endpoint, headers=headers, params=query_params, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    normalized = self._normalize_openai_response(data, fallback_model=candidate_model)
                    tracker.record_success(candidate_provider, candidate_model, latency_ms=(time.time() - start_t) * 1000.0)
                    return self._attach_resolved_agent(normalized, candidate_config, candidate_model, endpoint)
                except Exception as error:
                    last_error = error
                    if not self._is_transient_openai_error(error):
                        tracker.record_failure(candidate_provider, candidate_model, error=str(error))
                        raise
                    if attempt >= int(retry_settings["retry_count"]):
                        tracker.record_failure(candidate_provider, candidate_model, error=str(error))
                        break
                    time.sleep(self._compute_retry_delay(attempt, retry_settings))

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI-compatible 调用失败，未返回结果。")

    def _call_anthropic(
        self,
        agent_config: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        system_prompt, conversational_messages = self._split_system_messages(messages)
        last_error: Exception | None = None
        tracker = get_tracker()

        for candidate_config in self._iter_model_candidates(agent_config, primary_model=model):
            candidate_model = str(candidate_config.get("model_name") or model)
            candidate_provider = str(candidate_config.get("provider") or "anthropic")
            try:
                endpoint = self._resolve_anthropic_endpoint(candidate_config)
            except Exception as e:
                last_error = e
                tracker.record_failure(candidate_provider, candidate_model, error=str(e))
                continue
            api_key = self._resolve_api_key(candidate_config)
            auth_header = candidate_config.get("auth_header", "x-api-key")
            auth_scheme = candidate_config.get("auth_scheme", "")
            headers = {
                "Content-Type": "application/json",
                "anthropic-version": str(candidate_config.get("anthropic_version", "2023-06-01")),
                **candidate_config.get("headers", {}),
            }
            if api_key:
                headers[auth_header] = f"{auth_scheme} {api_key}".strip() if auth_scheme else api_key

            payload: dict[str, Any] = {
                "model": candidate_model,
                "messages": conversational_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **candidate_config.get("extra_body", {}),
            }
            if system_prompt:
                payload["system"] = system_prompt
            if tools is not None:
                payload["tools"] = tools

            query_params = candidate_config.get("query_params") or {}
            retry_settings = self._resolve_http_retry_settings(candidate_config)
            client = self._get_http_client(candidate_config)

            switched_to_next = False
            for attempt in range(1, int(retry_settings["retry_count"]) + 1):
                start_t = time.time()
                try:
                    response = client.post(endpoint, headers=headers, params=query_params, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    normalized = self._normalize_anthropic_response(data, fallback_model=candidate_model)
                    tracker.record_success(candidate_provider, candidate_model, latency_ms=(time.time() - start_t) * 1000.0)
                    return self._attach_resolved_agent(normalized, candidate_config, candidate_model, endpoint)
                except httpx.HTTPStatusError as error:
                    body_snippet = ""
                    try:
                        body_snippet = (error.response.text or "")[:240]
                    except Exception:
                        pass
                    enriched = httpx.HTTPStatusError(
                        f"{error} body={body_snippet}",
                        request=error.request,
                        response=error.response,
                    )
                    last_error = enriched
                    status = error.response.status_code
                    if status in {408, 409, 429, 500, 502, 503, 504}:
                        if attempt >= int(retry_settings["retry_count"]):
                            tracker.record_failure(candidate_provider, candidate_model, error=str(enriched))
                            switched_to_next = True
                            break
                        time.sleep(self._compute_retry_delay(attempt, retry_settings))
                        continue
                    # Non-transient (400/401/402/403): switch to next candidate
                    tracker.record_failure(candidate_provider, candidate_model, error=str(enriched))
                    switched_to_next = True
                    break
                except Exception as error:
                    last_error = error
                    if not self._is_transient_openai_error(error):
                        tracker.record_failure(candidate_provider, candidate_model, error=str(error))
                        switched_to_next = True
                        break
                    if attempt >= int(retry_settings["retry_count"]):
                        tracker.record_failure(candidate_provider, candidate_model, error=str(error))
                        switched_to_next = True
                        break
                    time.sleep(self._compute_retry_delay(attempt, retry_settings))
            if switched_to_next:
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("Anthropic-compatible 调用失败，未返回结果。")

    def _resolve_api_key(self, agent_config: dict[str, Any]) -> str | None:
        api_key = agent_config.get("api_key")
        if api_key:
            return str(api_key)
        api_key_env = agent_config.get("api_key_env")
        if api_key_env:
            return os.environ.get(str(api_key_env))
        return None

    def _resolve_openai_endpoint(self, agent_config: dict[str, Any]) -> str:
        endpoint = agent_config.get("endpoint")
        if endpoint:
            if str(endpoint).startswith("http"):
                return str(endpoint)
            base_url = agent_config.get("base_url")
            if not base_url:
                raise ValueError("openai provider 缺少 base_url。")
            return f"{str(base_url).rstrip('/')}/{str(endpoint).lstrip('/')}"

        base_url = agent_config.get("base_url")
        if not base_url:
            raise ValueError("openai provider 缺少 base_url 或 endpoint。")
        normalized = str(base_url).rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    def _resolve_anthropic_endpoint(self, agent_config: dict[str, Any]) -> str:
        endpoint = agent_config.get("endpoint")
        if endpoint:
            if str(endpoint).startswith("http"):
                return str(endpoint)
            base_url = agent_config.get("base_url")
            if not base_url:
                raise ValueError("anthropic provider 缺少 base_url。")
            return f"{str(base_url).rstrip('/')}/{str(endpoint).lstrip('/')}"

        base_url = agent_config.get("base_url")
        if not base_url:
            raise ValueError("anthropic provider 缺少 base_url 或 endpoint。")
        normalized = str(base_url).rstrip("/")
        if normalized.endswith("/v1/messages") or normalized.endswith("/messages"):
            return normalized
        return f"{normalized}/v1/messages"

    def _normalize_openai_message_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text = item.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                    elif isinstance(item.get("text"), str):
                        parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts).strip()
        if content is None:
            return ""
        return str(content)

    def _normalize_openai_response(self, data: dict[str, Any], fallback_model: str) -> dict[str, Any]:
        choices = data.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}
        normalized_message: dict[str, Any] = {
            "role": message.get("role", "assistant"),
            "content": self._normalize_openai_message_content(message.get("content")),
        }
        if message.get("tool_calls"):
            normalized_message["tool_calls"] = message["tool_calls"]
        return {
            "message": normalized_message,
            "model": data.get("model", fallback_model),
            "usage": data.get("usage"),
            "raw": data,
        }

    def _normalize_anthropic_response(self, data: dict[str, Any], fallback_model: str) -> dict[str, Any]:
        content_blocks = data.get("content") or []
        parts: list[str] = []
        if isinstance(content_blocks, list):
            for item in content_blocks:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(item, str):
                    parts.append(item)
        elif isinstance(content_blocks, str):
            parts.append(content_blocks)

        return {
            "message": {
                "role": data.get("role", "assistant"),
                "content": "".join(parts).strip(),
            },
            "model": data.get("model", fallback_model),
            "usage": data.get("usage"),
            "raw": data,
        }
