from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    import ollama
except ImportError:
    ollama = None  # type: ignore[assignment]

BASELINE_PROFILES = {
    "ollama-qwen25-7b": {
        "provider": "ollama",
        "model_name": "qwen2.5:7b",
        "temperature": 0.0,
        "max_tokens": 512,
    },
    # Legacy profile kept for historical result replay; no longer the default
    # benchmark target.
    "local-qwen35-27b": {
        "provider": "openai_compatible",
        "model_name": "Qwen3.5-27B.Q4_K_M.gguf",
        "base_url": "http://127.0.0.1:8081/v1",
        "temperature": 0.0,
        "max_tokens": 512,
        "timeout_seconds": 600,
    },
}


def _normalize_message_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        marker = "最终答案："
        if marker in reasoning:
            return reasoning.split(marker)[-1].strip()
        return reasoning.strip()

    return ""


class BaselineChatModel:
    def __init__(self, profile: str = "ollama-qwen25-7b", overrides: dict[str, Any] | None = None) -> None:
        if profile not in BASELINE_PROFILES:
            raise KeyError(f"未知 baseline profile: {profile}")
        config = deepcopy(BASELINE_PROFILES[profile])
        if overrides:
            config.update(overrides)
        self.profile = profile
        self.config = config

    def _call_ollama(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        response = ollama.chat(
            model=self.config["model_name"],
            messages=messages,
            options={
                "temperature": self.config.get("temperature", 0.0),
                "num_predict": self.config.get("max_tokens", 512),
            },
        )
        return {
            "answer": response["message"]["content"].strip(),
            "usage": {
                key: response.get(key)
                for key in (
                    "prompt_eval_count",
                    "eval_count",
                    "total_duration",
                    "load_duration",
                    "prompt_eval_duration",
                    "eval_duration",
                )
                if response.get(key) is not None
            },
            "raw": response,
        }

    def _call_openai_compatible(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        base_url = str(self.config["base_url"]).rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        payload = {
            "model": self.config["model_name"],
            "messages": messages,
            "temperature": self.config.get("temperature", 0.0),
            "max_tokens": self.config.get("max_tokens", 512),
        }
        with httpx.Client(timeout=float(self.config.get("timeout_seconds", 180))) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}
        return {
            "answer": _normalize_message_content(message),
            "usage": data.get("usage"),
            "raw": data,
        }

    def complete_with_metadata(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        provider = self.config.get("provider", "ollama")
        started = time.perf_counter()
        if provider == "ollama":
            result = self._call_ollama(messages)
        elif provider == "openai_compatible":
            result = self._call_openai_compatible(messages)
        else:
            raise ValueError(f"Unsupported baseline provider: {provider}")
        result["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        result["provider"] = provider
        result["model_name"] = self.config["model_name"]
        return result

    def complete(self, messages: list[dict[str, str]]) -> str:
        return str(self.complete_with_metadata(messages)["answer"])


def baseline_ask(
    conversation: list[dict[str, str]],
    user_question: str,
    profile: str = "ollama-qwen25-7b",
    system_prompt: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> str:
    model = BaselineChatModel(profile=profile, overrides=overrides)
    messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    messages.extend(conversation)
    messages.append({"role": "user", "content": user_question})
    answer = model.complete(messages)
    conversation.append({"role": "user", "content": user_question})
    conversation.append({"role": "assistant", "content": answer})
    return answer


def baseline_ask_with_metrics(
    conversation: list[dict[str, str]],
    user_question: str,
    profile: str = "ollama-qwen25-7b",
    system_prompt: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = BaselineChatModel(profile=profile, overrides=overrides)
    messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    messages.extend(conversation)
    messages.append({"role": "user", "content": user_question})
    result = model.complete_with_metadata(messages)
    conversation.append({"role": "user", "content": user_question})
    conversation.append({"role": "assistant", "content": str(result["answer"])})
    return result


def interactive_baseline(profile: str = "ollama-qwen25-7b") -> None:
    conversation: list[dict[str, str]] = []
    print(f"Baseline Demo 已启动，profile={profile}，输入 exit 或 quit 退出。")
    while True:
        user_question = input("\n用户: ").strip()
        if user_question.lower() in {"exit", "quit"}:
            break

        answer = baseline_ask(conversation, user_question, profile=profile)
        print(f"助手: {answer}")


if __name__ == "__main__":
    interactive_baseline()
