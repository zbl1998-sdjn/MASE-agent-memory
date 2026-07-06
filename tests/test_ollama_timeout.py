"""Ollama 客户端超时与死锁自愈语义(2026-07-06 卸载死锁实录驱动)。

钉死三件事:①默认带 600s 读超时(拦"永不返回"的卸载死锁);②env/fallbacks
可配置、≤0 显式关闭回旧行为;③读超时不算 transient(重试只会再烧一个超时窗),
连接超时算 transient(服务重启窗口,等健康后重试自愈)。
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from mase import model_providers
from mase.model_http import ModelHTTPMixin
from mase.model_providers import ModelProviderMixin


class _TimeoutHarness(ModelProviderMixin, ModelHTTPMixin):
    """带真实分类器/超时解析的最小宿主,重试参数走 fallbacks。"""

    def __init__(self, fallbacks: dict[str, Any] | None = None) -> None:
        self.fallbacks: dict[str, Any] = fallbacks or {}

    def _resolve_ollama_base_url(self) -> str:
        return "http://127.0.0.1:11434"

    def _wait_for_ollama_ready(self) -> bool:
        return True


class _CapturingClient:
    """捕获构造参数的假 ollama.Client。"""

    captured: list[dict[str, Any]] = []

    def __init__(self, host: Any = None, timeout: Any = None) -> None:
        type(self).captured.append({"host": host, "timeout": timeout})

    def chat(self, **payload: Any) -> dict[str, Any]:
        del payload
        return {"message": {"content": "ok"}}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MASE_OLLAMA_TIMEOUT_S", raising=False)
    _CapturingClient.captured = []


def test_default_ollama_client_has_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_providers.ollama, "Client", _CapturingClient)
    harness = _TimeoutHarness()
    result = harness._call_ollama({}, "llama", [{"role": "user", "content": "hi"}], 0.0, 8)
    assert result["message"]["content"] == "ok"
    assert len(_CapturingClient.captured) == 1
    captured = _CapturingClient.captured[0]
    assert captured["host"] == "http://127.0.0.1:11434"
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["timeout"].read == 600.0
    assert captured["timeout"].connect == 10.0


def test_env_overrides_ollama_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_OLLAMA_TIMEOUT_S", "120")
    monkeypatch.setattr(model_providers.ollama, "Client", _CapturingClient)
    harness = _TimeoutHarness(fallbacks={"ollama_timeout_seconds": 45})
    harness._call_ollama({}, "llama", [{"role": "user", "content": "hi"}], 0.0, 8)
    assert _CapturingClient.captured[0]["timeout"].read == 120.0


def test_fallbacks_key_configures_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_providers.ollama, "Client", _CapturingClient)
    harness = _TimeoutHarness(fallbacks={"ollama_timeout_seconds": 45})
    harness._call_ollama({}, "llama", [{"role": "user", "content": "hi"}], 0.0, 8)
    assert _CapturingClient.captured[0]["timeout"].read == 45.0


def test_zero_timeout_restores_legacy_module_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_OLLAMA_TIMEOUT_S", "0")

    def _no_client(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("timeout disabled must not construct ollama.Client")

    chat_calls: list[dict[str, Any]] = []

    def _module_chat(**payload: Any) -> dict[str, Any]:
        chat_calls.append(payload)
        return {"message": {"content": "legacy"}}

    monkeypatch.setattr(model_providers.ollama, "Client", _no_client)
    monkeypatch.setattr(model_providers.ollama, "chat", _module_chat)
    harness = _TimeoutHarness()
    result = harness._call_ollama({}, "llama", [{"role": "user", "content": "hi"}], 0.0, 8)
    assert result["message"]["content"] == "legacy"
    assert len(chat_calls) == 1


def test_read_timeout_is_not_transient_but_connect_timeout_is() -> None:
    harness = _TimeoutHarness()
    assert harness._is_transient_ollama_error(httpx.ReadTimeout("The read operation timed out")) is False
    assert harness._is_transient_ollama_error(httpx.WriteTimeout("timed out")) is False
    assert harness._is_transient_ollama_error(httpx.PoolTimeout("timed out")) is False
    assert harness._is_transient_ollama_error(httpx.ConnectTimeout("timed out")) is True
    # 消息标记匹配区分大小写(既有行为):按真实 httpx/Windows 消息形态断言。
    assert harness._is_transient_ollama_error(httpx.ConnectError("Connection refused")) is True


def test_read_timeout_fails_fast_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    class _WedgedClient:
        def __init__(self, host: Any = None, timeout: Any = None) -> None:
            del host, timeout

        def chat(self, **payload: Any) -> dict[str, Any]:
            del payload
            attempts.append(1)
            raise httpx.ReadTimeout("The read operation timed out")

    monkeypatch.setattr(model_providers.ollama, "Client", _WedgedClient)
    harness = _TimeoutHarness(fallbacks={"ollama_retry_count": 6, "ollama_retry_delay": 0})
    with pytest.raises(httpx.ReadTimeout):
        harness._call_ollama({}, "llama", [{"role": "user", "content": "hi"}], 0.0, 8)
    assert len(attempts) == 1  # 卸载死锁不重试:重试只会再烧一个完整超时窗
