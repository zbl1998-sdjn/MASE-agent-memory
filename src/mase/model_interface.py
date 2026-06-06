"""模型调用门面：统一配置解析、系统提示注入、provider 调用与调用账本。

`ModelInterface` 是 router / notetaker / planner / executor 共用的模型边界。
它不决定业务路由，也不解析最终答案；它只负责把 agent 配置解析成一次安全、
可观测、可计费的模型请求。
"""
# 迁移到 src/ 布局后仍以仓库根目录为默认配置基准，兼容 editable install 与
# 旧版根目录 shim。
from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from datetime import timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

import httpx

from .cost_center import load_pricing_catalog
from .model_call_ledger import ModelCallLedgerMixin
from .model_http import ModelHTTPMixin
from .model_providers import ModelProviderMixin

BASE_DIR = Path(__file__).resolve().parents[2]
_LOCAL_PROVIDERS = {"ollama", "llama_cpp", "llamacpp", "llama.cpp", "local", "localhost"}
_TRUTHY = {"1", "true", "yes", "y", "on"}


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    """按显式参数、环境变量、当前工作目录、源码树、用户目录的顺序找配置。"""
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
    """加载项目级 env 文件，但不覆盖进程里已经显式设置的变量。"""
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
    """返回运行产物根目录；未设置时继续使用配置中的相对路径。"""
    raw = os.environ.get("MASE_RUNS_DIR")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def cloud_models_allowed() -> bool:
    """云模型总开关：只有用户显式批准后才允许非本地 provider 出网调用。"""
    return str(os.environ.get("MASE_ALLOW_CLOUD_MODELS") or "").strip().lower() in _TRUTHY


def _enforce_cloud_model_policy(provider: str, agent_type: str, mode: str | None, model_name: str) -> None:
    """在真正发起 provider 请求前执行最后一道云模型审批检查。"""
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
    """解析 memory 路径，并在设置 `MASE_RUNS_DIR` 时把默认产物移出源码树。"""
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


class ModelInterface(ModelCallLedgerMixin, ModelHTTPMixin, ModelProviderMixin):
    """模型请求统一门面。

    继承的三个 mixin 分别处理调用账本、HTTP 客户端/重试参数、provider 协议。
    本类只维护配置、HTTP client 生命周期和 chat() 的统一入口。
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = resolve_config_path(config_path)
        self.call_log: list[dict[str, Any]] = []
        self._http_clients: dict[str, httpx.Client] = {}
        self.reload()

    def reload(self) -> None:
        """重新加载配置与价格目录，并关闭旧 HTTP client 以免连接池配置漂移。"""
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

    def get_agent_config(self, agent_type: str) -> dict[str, Any]:
        if agent_type not in self.models_config:
            raise KeyError(f"配置中不存在智能体: {agent_type}")
        return self.models_config[agent_type]

    def _merge_config_override(self, base_config: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """合并 mode / fallback 覆盖配置。

        headers、query_params、extra_body 做浅合并；其他字段直接覆盖，避免嵌套
        provider 参数出现半旧半新的混合状态。
        """
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
        """取 agent 的最终配置，支持 mode 继承另一个 mode。"""
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

    def get_system_prompt(
        self,
        agent_type: str,
        mode: str | None = None,
        prompt_key: str = "system_prompt",
    ) -> str | None:
        agent_config = self.get_effective_agent_config(agent_type, mode=mode)
        return agent_config.get(prompt_key)

    def inject_system_prompt(self, messages: list[dict[str, Any]], system_prompt: str) -> list[dict[str, Any]]:
        """把系统提示注入消息列表；已有 system 消息则替换，缺失则前置。"""
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
        """统一模型调用入口。

        关键边界：
        1. 先解析最终 agent/mode 配置；
        2. 非本地 provider 必须通过云模型审批；
        3. 系统提示在这里统一注入；
        4. provider 返回后立即记录调用账本，供 trace、成本中心和审计使用。
        """
        agent_config = self.get_effective_agent_config(agent_type, mode=mode)
        provider = agent_config.get("provider", "ollama")
        model_name = agent_config["model_name"]
        _enforce_cloud_model_policy(str(provider), agent_type, mode, str(model_name))
        temperature = agent_config.get("temperature", 0.7)
        max_tokens = agent_config.get("max_tokens", 512)
        # MC self-consistency 钩子：只有显式设置环境变量才覆盖温度，并且只影响
        # executor，避免 router/notetaker 的稳定性被评测调参误伤。
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
