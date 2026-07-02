"""Provider 协议 mixin：封装 Ollama、OpenAI-compatible、Anthropic-compatible 调用。

本模块只负责把统一的 agent 配置翻译成各 provider 的请求/响应格式，并处理
候选模型 fallback。HTTP client、重试参数和成本账本分别由其它 mixin 负责。
"""
from __future__ import annotations

import os
import re
import time
from copy import deepcopy
from typing import Any

import httpx
import ollama

from .health_tracker import get_tracker


class ModelProviderMixin:
    """为 `ModelInterface` 提供具体 provider 的调用实现。"""

    fallbacks: dict[str, Any]

    def _split_system_messages(self: Any, messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        """Anthropic API 单独传 system；这里把 system 消息从对话消息中拆出。

        system 字段在 Anthropic API 里必须是纯文本，因此 system 消息的 content
        始终被压平成字符串。conversational 消息则原样透传：字符串/None 按原有
        行为归一化，但结构化 content（例如多模态 content blocks 列表）不能被
        `str()` 压成 repr 字符串，否则会破坏 Anthropic 多模态请求体的形状。
        """
        system_parts: list[str] = []
        conversational: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "")
            content = message.get("content")
            if role == "system":
                normalized_system = content if isinstance(content, str) else str(content or "")
                if normalized_system.strip():
                    system_parts.append(normalized_system)
                continue
            if content is None or isinstance(content, str):
                normalized_content: Any = content or ""
            else:
                normalized_content = content
            conversational.append(
                {
                    "role": role or "user",
                    "content": normalized_content,
                }
            )
        system_prompt = "\n\n".join(part for part in system_parts if part.strip()) or None
        return system_prompt, conversational

    def _call_ollama(
        self: Any,
        agent_config: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """调用本地 Ollama，并在瞬时连接错误时做有限重试。"""
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

    def _resolve_ollama_keep_alive(self: Any, agent_config: dict[str, Any]) -> str | int | float | None:
        """解析 keep_alive，环境变量优先，兼容数字和 Ollama 字符串格式。"""
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

    def _iter_model_candidates(self: Any, agent_config: dict[str, Any], primary_model: str) -> list[dict[str, Any]]:
        """生成主模型、配置 fallback、全局本地 fallback 的有序候选列表。"""
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

        local_fallback = self.fallbacks.get("local_fallback")
        if isinstance(local_fallback, dict) and local_fallback.get("model_name") and local_fallback.get("provider"):
            already_present = any(
                str(c.get("provider")) == str(local_fallback.get("provider"))
                and str(c.get("model_name")) == str(local_fallback.get("model_name"))
                for c in candidates
            )
            if not already_present:
                candidates.append(self._merge_config_override(deepcopy(primary_config), local_fallback))

        if len(candidates) > 1:
            try:
                # 健康追踪器按近期成功率/延迟排序候选；失败时保持配置顺序。
                candidates = get_tracker().sort_candidates(candidates)
            except Exception:
                pass
        return candidates

    def _attach_resolved_agent(
        self: Any,
        response: dict[str, Any],
        agent_config: dict[str, Any],
        model_name: str,
        endpoint: str,
    ) -> dict[str, Any]:
        """把最终命中的 provider/model/endpoint 写回响应，供调用账本归因。"""
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
        self: Any,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        del messages
        raise NotImplementedError(
            f"provider=llama_cpp 已预留接口，但当前尚未接入。model={model}, max_tokens={max_tokens}, temperature={temperature}"
        )

    def _call_openai(
        self: Any,
        agent_config: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """调用 OpenAI-compatible chat/completions 接口。

        每个候选模型内部先按重试策略处理瞬时错误；候选耗尽后才把最后一次错误
        抛给上层。
        """
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

            # extra_body 允许兼容供应商私有字段，但统一入口仍固定 messages /
            # temperature / max_tokens 这些基础形状。
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
        self: Any,
        agent_config: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """调用 Anthropic-compatible messages 接口，并复用候选 fallback 机制。"""
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
                    # HTTPStatusError 默认信息常缺 body；补一小段响应体帮助定位
                    # 鉴权/限流/供应商错误，同时避免把整段响应写进日志。
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

    def _resolve_api_key(self: Any, agent_config: dict[str, Any]) -> str | None:
        """优先读取显式 api_key，其次读取 api_key_env 指向的环境变量。"""
        api_key = agent_config.get("api_key")
        if api_key:
            return str(api_key)
        api_key_env = agent_config.get("api_key_env")
        if api_key_env:
            return os.environ.get(str(api_key_env))
        return None

    def _resolve_openai_endpoint(self: Any, agent_config: dict[str, Any]) -> str:
        """解析 OpenAI-compatible endpoint，允许 base_url 或完整 endpoint。"""
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

    def _resolve_anthropic_endpoint(self: Any, agent_config: dict[str, Any]) -> str:
        """解析 Anthropic-compatible endpoint，默认补 `/v1/messages`。"""
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

    def _normalize_openai_message_content(self: Any, content: Any) -> str:
        """把 OpenAI 多模态/分块 content 收敛为文本，供下游统一抽取答案。"""
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

    def _normalize_openai_response(self: Any, data: dict[str, Any], fallback_model: str) -> dict[str, Any]:
        """把 OpenAI-compatible 响应归一化成内部 message/usage/raw 结构。"""
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

    def _normalize_anthropic_response(self: Any, data: dict[str, Any], fallback_model: str) -> dict[str, Any]:
        """把 Anthropic content blocks 归一化成内部 message/usage/raw 结构。"""
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
