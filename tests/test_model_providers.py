from __future__ import annotations

from typing import Any

import httpx
import pytest

from mase import model_providers
from mase.model_providers import ModelProviderMixin


class DummyProvider(ModelProviderMixin):
    def __init__(self) -> None:
        self.fallbacks: dict[str, Any] = {}

    def _merge_config_override(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        merged.update(override)
        return merged

    def _resolve_http_retry_settings(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        return {
            "retry_count": agent_config.get("retry_count", 1),
            "retry_base_delay": 0.0,
            "retry_max_delay": 0.0,
            "retry_jitter": 0.0,
            "retry_backoff_multiplier": 1.0,
        }

    def _get_http_client(self, agent_config: dict[str, Any]) -> Any:
        return agent_config["client"]

    def _compute_retry_delay(self, attempt: int, retry_settings: dict[str, Any]) -> float:
        del attempt, retry_settings
        return 0.0

    def _is_transient_openai_error(self, error: Exception) -> bool:
        if isinstance(error, httpx.TimeoutException | httpx.TransportError):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in {408, 409, 429, 500, 502, 503, 504}
        return False

    def _is_transient_ollama_error(self, error: Exception) -> bool:
        return "refused" in str(error).lower() or isinstance(error, httpx.HTTPError)

    def _wait_for_ollama_ready(self) -> bool:
        return True

    def _resolve_ollama_base_url(self) -> str:
        return "http://127.0.0.1:11434"


class FakeTracker:
    def __init__(self) -> None:
        self.successes: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str, str]] = []

    def sort_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return candidates

    def record_success(self, provider: str, model: str, *, latency_ms: float) -> None:
        assert latency_ms >= 0
        self.successes.append((provider, model))

    def record_failure(self, provider: str, model: str, *, error: str) -> None:
        self.failures.append((provider, model, error))


class FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200, text: str = "") -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.request = httpx.Request("POST", "https://api.test")
        self.response = httpx.Response(status_code, request=self.request, text=text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=self.request, response=self.response)

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.posts: list[dict[str, Any]] = []

    def __deepcopy__(self, memo: dict[int, Any]) -> FakeClient:
        del memo
        return self

    def post(self, endpoint: str, **kwargs: Any) -> FakeResponse:
        self.posts.append({"endpoint": endpoint, **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_split_system_messages_keeps_conversation_order() -> None:
    provider = DummyProvider()

    system_prompt, messages = provider._split_system_messages(
        [
            {"role": "system", "content": "Policy A"},
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "Policy B"},
            {"role": "", "content": None},
        ]
    )

    assert system_prompt == "Policy A\n\nPolicy B"
    assert messages == [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": ""},
    ]


def test_split_system_messages_preserves_multimodal_content_blocks() -> None:
    """Anthropic-style content blocks (e.g. text+image) must pass through
    unchanged for conversational messages; only plain-text/None content is
    normalized to a string. System messages remain flattened to text because
    the Anthropic API's ``system`` field is always a plain string."""
    provider = DummyProvider()

    blocks = [
        {"type": "text", "text": "what is in this image?"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
    ]

    system_prompt, messages = provider._split_system_messages(
        [
            {"role": "system", "content": "Policy A"},
            {"role": "user", "content": blocks},
        ]
    )

    assert system_prompt == "Policy A"
    assert messages == [{"role": "user", "content": blocks}]


def test_resolve_keep_alive_prefers_env_then_config(monkeypatch) -> None:
    provider = DummyProvider()
    provider.fallbacks = {"ollama_keep_alive": "5m"}

    monkeypatch.setenv("MASE_OLLAMA_KEEP_ALIVE", "42")
    assert provider._resolve_ollama_keep_alive({"keep_alive": "1m"}) == 42

    monkeypatch.setenv("MASE_OLLAMA_KEEP_ALIVE", "3.5")
    assert provider._resolve_ollama_keep_alive({}) == 3.5

    monkeypatch.delenv("MASE_OLLAMA_KEEP_ALIVE", raising=False)
    assert provider._resolve_ollama_keep_alive({"keep_alive": "10m"}) == "10m"
    assert provider._resolve_ollama_keep_alive({}) == "5m"


def test_iter_model_candidates_includes_config_and_local_fallback(monkeypatch) -> None:
    class FakeTracker:
        def sort_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return candidates

    monkeypatch.setattr(model_providers, "get_tracker", lambda: FakeTracker())
    provider = DummyProvider()
    provider.fallbacks = {"local_fallback": {"provider": "ollama", "model_name": "local-safe"}}

    candidates = provider._iter_model_candidates(
        {
            "provider": "openai",
            "base_url": "https://example.test/v1",
            "fallback_models": [
                "secondary",
                {"model_name": "third", "base_url": "https://third.test/v1"},
            ],
        },
        primary_model="primary",
    )

    assert [candidate["model_name"] for candidate in candidates] == ["primary", "secondary", "third", "local-safe"]
    assert all("fallback_models" not in candidate for candidate in candidates)


def test_endpoint_api_key_and_response_normalization(monkeypatch) -> None:
    provider = DummyProvider()
    monkeypatch.setenv("MODEL_KEY", "secret-value")

    assert provider._resolve_api_key({"api_key": "direct", "api_key_env": "MODEL_KEY"}) == "direct"
    assert provider._resolve_api_key({"api_key_env": "MODEL_KEY"}) == "secret-value"
    assert provider._resolve_api_key({}) is None
    assert provider._resolve_openai_endpoint({"base_url": "https://api.test/v1"}) == "https://api.test/v1/chat/completions"
    assert provider._resolve_openai_endpoint({"endpoint": "chat/completions", "base_url": "https://api.test/v1"}) == (
        "https://api.test/v1/chat/completions"
    )
    assert provider._resolve_anthropic_endpoint({"base_url": "https://anthropic.test"}) == "https://anthropic.test/v1/messages"
    assert provider._resolve_anthropic_endpoint({"endpoint": "v1/messages", "base_url": "https://anthropic.test"}) == (
        "https://anthropic.test/v1/messages"
    )
    with pytest.raises(ValueError):
        provider._resolve_openai_endpoint({})
    with pytest.raises(ValueError):
        provider._resolve_anthropic_endpoint({})

    assert provider._normalize_openai_message_content([{"type": "text", "text": "hi"}, {"text": " there"}, " friend"]) == (
        "hi there friend"
    )
    openai = provider._normalize_openai_response(
        {
            "model": "actual",
            "choices": [{"message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}],
            "usage": {"prompt_tokens": 1},
        },
        fallback_model="fallback",
    )
    assert openai["message"] == {"role": "assistant", "content": "done"}
    assert openai["model"] == "actual"

    anthropic = provider._normalize_anthropic_response(
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}, {"type": "text", "text": " world"}]},
        fallback_model="fallback",
    )
    assert anthropic["message"]["content"] == "hello world"
    assert anthropic["model"] == "fallback"


def test_attach_resolved_agent_and_llama_cpp_placeholder() -> None:
    provider = DummyProvider()
    response = provider._attach_resolved_agent(
        {"message": {"content": "ok"}},
        {
            "provider": "openai",
            "base_url": "https://api.test",
            "cost_per_1k_tokens": 0.1,
        },
        "model-a",
        "https://api.test/chat/completions",
    )

    assert response["resolved_agent"]["provider"] == "openai"
    assert response["resolved_agent"]["model_name"] == "model-a"
    with pytest.raises(NotImplementedError):
        provider._call_llama_cpp("model", [], 0.0, 10)


def test_call_ollama_retries_transient_errors_and_preserves_payload(monkeypatch) -> None:
    provider = DummyProvider()
    provider.fallbacks = {
        "ollama_retry_count": 2,
        "ollama_retry_delay": 0,
        "ollama_wait_for_healthy": True,
    }
    calls: list[dict[str, Any]] = []

    def fake_chat(**payload: Any) -> dict[str, Any]:
        calls.append(payload)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused")
        return {"message": {"content": "ok"}}

    class _FakeOllamaClient:
        def __init__(self, host: Any = None, timeout: Any = None) -> None:
            del host, timeout

        def chat(self, **payload: Any) -> dict[str, Any]:
            return fake_chat(**payload)

    monkeypatch.setattr(model_providers.ollama, "Client", _FakeOllamaClient)
    monkeypatch.setattr(model_providers.time, "sleep", lambda delay: None)
    result = provider._call_ollama(
        {"ollama_options": {"top_k": 5}, "extra_body": {"stream": False}, "keep_alive": "30m"},
        "llama",
        [{"role": "user", "content": "hi"}],
        0.2,
        64,
        tools=[{"type": "function"}],
    )

    assert result["message"]["content"] == "ok"
    assert len(calls) == 2
    assert calls[1]["model"] == "llama"
    assert calls[1]["options"] == {"temperature": 0.2, "num_predict": 64, "top_k": 5}
    assert calls[1]["keep_alive"] == "30m"
    assert calls[1]["tools"] == [{"type": "function"}]
    assert calls[1]["stream"] is False


def test_call_openai_success_uses_configured_headers_tools_and_query(monkeypatch) -> None:
    tracker = FakeTracker()
    monkeypatch.setattr(model_providers, "get_tracker", lambda: tracker)
    provider = DummyProvider()
    client = FakeClient(
        [
            FakeResponse(
                {
                    "model": "actual-model",
                    "choices": [{"message": {"role": "assistant", "content": "done"}}],
                    "usage": {"total_tokens": 9},
                }
            )
        ]
    )

    response = provider._call_openai(
        {
            "provider": "openai",
            "model_name": "primary",
            "base_url": "https://api.test/v1",
            "api_key": "direct-key",
            "auth_header": "X-Key",
            "auth_scheme": "",
            "headers": {"X-Trace": "abc"},
            "query_params": {"api-version": "2024-01-01"},
            "extra_body": {"response_format": {"type": "json_object"}},
            "client": client,
        },
        "primary",
        [{"role": "user", "content": "hi"}],
        0.3,
        128,
        tools=[{"type": "function", "function": {"name": "lookup"}}],
    )

    post = client.posts[0]
    assert post["endpoint"] == "https://api.test/v1/chat/completions"
    assert post["headers"]["X-Key"] == "direct-key"
    assert post["headers"]["X-Trace"] == "abc"
    assert post["params"] == {"api-version": "2024-01-01"}
    assert post["json"]["tool_choice"] == "auto"
    assert post["json"]["response_format"] == {"type": "json_object"}
    assert response["message"]["content"] == "done"
    assert response["resolved_agent"]["model_name"] == "primary"
    assert tracker.successes == [("openai", "primary")]


def test_call_openai_tries_next_candidate_after_transient_failure(monkeypatch) -> None:
    tracker = FakeTracker()
    monkeypatch.setattr(model_providers, "get_tracker", lambda: tracker)
    provider = DummyProvider()
    first_client = FakeClient([httpx.TimeoutException("timeout")])
    second_client = FakeClient(
        [
            FakeResponse(
                {
                    "choices": [{"message": {"content": "fallback answer"}}],
                    "usage": {"completion_tokens": 2},
                }
            )
        ]
    )

    response = provider._call_openai(
        {
            "provider": "openai",
            "base_url": "https://primary.test/v1",
            "client": first_client,
            "retry_count": 1,
            "fallback_models": [
                {
                    "provider": "openai",
                    "model_name": "fallback-model",
                    "base_url": "https://fallback.test/v1",
                    "client": second_client,
                }
            ],
        },
        "primary-model",
        [{"role": "user", "content": "hi"}],
        0.0,
        32,
    )

    assert response["message"]["content"] == "fallback answer"
    assert response["resolved_agent"]["model_name"] == "fallback-model"
    assert tracker.failures == [("openai", "primary-model", "timeout")]
    assert tracker.successes == [("openai", "fallback-model")]


def test_call_anthropic_success_splits_system_and_normalizes_blocks(monkeypatch) -> None:
    tracker = FakeTracker()
    monkeypatch.setattr(model_providers, "get_tracker", lambda: tracker)
    provider = DummyProvider()
    client = FakeClient(
        [
            FakeResponse(
                {
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [{"type": "text", "text": "hello"}, {"type": "text", "text": " world"}],
                    "usage": {"input_tokens": 3},
                }
            )
        ]
    )

    response = provider._call_anthropic(
        {
            "provider": "anthropic",
            "base_url": "https://anthropic.test",
            "api_key": "anthropic-key",
            "headers": {"X-Trace": "abc"},
            "anthropic_version": "2024-01-01",
            "client": client,
        },
        "claude-test",
        [
            {"role": "system", "content": "Policy"},
            {"role": "user", "content": "hi"},
        ],
        0.1,
        100,
        tools=[{"name": "lookup"}],
    )

    post = client.posts[0]
    assert post["endpoint"] == "https://anthropic.test/v1/messages"
    assert post["headers"]["x-api-key"] == "anthropic-key"
    assert post["headers"]["anthropic-version"] == "2024-01-01"
    assert post["json"]["system"] == "Policy"
    assert post["json"]["messages"] == [{"role": "user", "content": "hi"}]
    assert post["json"]["tools"] == [{"name": "lookup"}]
    assert response["message"]["content"] == "hello world"
    assert tracker.successes == [("anthropic", "claude-test")]


def test_call_anthropic_enriches_status_errors_and_tries_next_candidate(monkeypatch) -> None:
    tracker = FakeTracker()
    monkeypatch.setattr(model_providers, "get_tracker", lambda: tracker)
    provider = DummyProvider()
    bad_client = FakeClient([FakeResponse({}, status_code=401, text="no auth")])
    good_client = FakeClient([FakeResponse({"content": "plain text"})])

    response = provider._call_anthropic(
        {
            "provider": "anthropic",
            "base_url": "https://bad.test",
            "client": bad_client,
            "fallback_models": [
                {
                    "provider": "anthropic",
                    "model_name": "backup",
                    "base_url": "https://good.test/messages",
                    "client": good_client,
                }
            ],
        },
        "primary",
        [{"role": "user", "content": "hi"}],
        0.0,
        32,
    )

    assert response["message"]["content"] == "plain text"
    assert response["resolved_agent"]["model_name"] == "backup"
    assert tracker.failures[0][0:2] == ("anthropic", "primary")
    assert "body=no auth" in tracker.failures[0][2]


def test_keep_alive_candidates_endpoints_and_normalizers_cover_edge_branches(monkeypatch) -> None:
    provider = DummyProvider()
    provider.fallbacks = {}
    monkeypatch.delenv("MASE_OLLAMA_KEEP_ALIVE", raising=False)

    assert provider._resolve_ollama_keep_alive({}) is None
    monkeypatch.setenv("MASE_OLLAMA_KEEP_ALIVE", "   ")
    assert provider._resolve_ollama_keep_alive({"keep_alive": "   "}) is None

    class FailingTracker:
        def sort_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
            raise RuntimeError("tracker down")

    monkeypatch.setattr(model_providers, "get_tracker", lambda: FailingTracker())
    candidates = provider._iter_model_candidates(
        {
            "provider": "openai",
            "base_url": "https://api.test/v1",
            "fallback_models": [object(), {"model_name": "backup"}],
        },
        primary_model="primary",
    )
    assert [candidate["model_name"] for candidate in candidates] == ["primary", "backup"]

    assert provider._resolve_openai_endpoint({"endpoint": "https://full.test/chat/completions"}) == (
        "https://full.test/chat/completions"
    )
    assert provider._resolve_openai_endpoint({"base_url": "https://api.test/v1/chat/completions"}) == (
        "https://api.test/v1/chat/completions"
    )
    assert provider._resolve_anthropic_endpoint({"endpoint": "https://full.test/v1/messages"}) == (
        "https://full.test/v1/messages"
    )
    assert provider._resolve_anthropic_endpoint({"base_url": "https://anthropic.test/messages"}) == (
        "https://anthropic.test/messages"
    )
    assert provider._normalize_openai_message_content(None) == ""
    assert provider._normalize_openai_message_content({"unexpected": "shape"}) == "{'unexpected': 'shape'}"
    normalized = provider._normalize_openai_response(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": "call_1"}],
                    }
                }
            ]
        },
        fallback_model="fallback",
    )
    assert normalized["message"]["content"] == ""
    assert normalized["message"]["tool_calls"] == [{"id": "call_1"}]
    assert provider._normalize_anthropic_response({"content": None}, fallback_model="fallback")["message"]["content"] == ""


def test_call_ollama_reraises_non_transient_errors(monkeypatch) -> None:
    provider = DummyProvider()
    provider.fallbacks = {"ollama_retry_count": 3, "ollama_retry_delay": 0}

    def fail_chat(**payload: Any) -> dict[str, Any]:
        del payload
        raise OSError("disk unavailable")

    class _FailingOllamaClient:
        def __init__(self, host: Any = None, timeout: Any = None) -> None:
            del host, timeout

        def chat(self, **payload: Any) -> dict[str, Any]:
            return fail_chat(**payload)

    monkeypatch.setattr(model_providers.ollama, "Client", _FailingOllamaClient)
    with pytest.raises(OSError, match="disk unavailable"):
        provider._call_ollama({}, "llama", [{"role": "user", "content": "hi"}], 0.0, 10)


def test_call_openai_reraises_non_transient_status_and_retries_transient(monkeypatch) -> None:
    tracker = FakeTracker()
    monkeypatch.setattr(model_providers, "get_tracker", lambda: tracker)
    monkeypatch.setattr(model_providers.time, "sleep", lambda delay: None)
    provider = DummyProvider()

    bad_client = FakeClient([FakeResponse({}, status_code=400, text="bad request")])
    with pytest.raises(httpx.HTTPStatusError):
        provider._call_openai(
            {
                "provider": "openai",
                "base_url": "https://api.test/v1",
                "client": bad_client,
                "retry_count": 2,
            },
            "primary",
            [{"role": "user", "content": "hi"}],
            0.0,
            16,
        )
    assert tracker.failures[-1][0:2] == ("openai", "primary")

    retry_client = FakeClient(
        [
            httpx.TimeoutException("temporary timeout"),
            FakeResponse({"choices": [{"message": {"content": "after retry"}}]}),
        ]
    )
    response = provider._call_openai(
        {
            "provider": "openai",
            "base_url": "https://api.test/v1",
            "client": retry_client,
            "retry_count": 2,
        },
        "retry-model",
        [{"role": "user", "content": "hi"}],
        0.0,
        16,
    )
    assert len(retry_client.posts) == 2
    assert response["message"]["content"] == "after retry"


def test_call_anthropic_skips_bad_endpoint_retries_status_and_raises_last_transient(monkeypatch) -> None:
    tracker = FakeTracker()
    monkeypatch.setattr(model_providers, "get_tracker", lambda: tracker)
    monkeypatch.setattr(model_providers.time, "sleep", lambda delay: None)
    provider = DummyProvider()

    good_client = FakeClient([FakeResponse({"content": [{"type": "text", "text": "fallback ok"}]})])
    response = provider._call_anthropic(
        {
            "provider": "anthropic",
            "client": FakeClient([]),
            "fallback_models": [
                {
                    "provider": "anthropic",
                    "model_name": "backup",
                    "base_url": "https://good.test",
                    "client": good_client,
                }
            ],
        },
        "primary",
        [{"role": "user", "content": "hi"}],
        0.0,
        16,
    )
    assert response["message"]["content"] == "fallback ok"
    assert tracker.failures[0][0:2] == ("anthropic", "primary")

    retry_client = FakeClient(
        [
            FakeResponse({}, status_code=503, text="try later"),
            FakeResponse({"content": "anthropic retry ok"}),
        ]
    )
    retry_response = provider._call_anthropic(
        {
            "provider": "anthropic",
            "base_url": "https://retry.test",
            "client": retry_client,
            "retry_count": 2,
        },
        "retry-model",
        [{"role": "user", "content": "hi"}],
        0.0,
        16,
    )
    assert len(retry_client.posts) == 2
    assert retry_response["message"]["content"] == "anthropic retry ok"

    exhausted = FakeClient([httpx.TimeoutException("timeout forever")])
    with pytest.raises(httpx.TimeoutException, match="timeout forever"):
        provider._call_anthropic(
            {
                "provider": "anthropic",
                "base_url": "https://retry.test",
                "client": exhausted,
                "retry_count": 1,
            },
            "exhausted",
            [{"role": "user", "content": "hi"}],
            0.0,
            16,
        )
    assert tracker.failures[-1][0:2] == ("anthropic", "exhausted")
