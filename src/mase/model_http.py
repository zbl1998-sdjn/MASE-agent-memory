from __future__ import annotations

import json
import random
import time
from typing import Any

import httpx


class ModelHTTPMixin:
    fallbacks: dict[str, Any]
    _http_clients: dict[str, httpx.Client]

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

    def _resolve_ollama_base_url(self) -> str:
        import os

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
