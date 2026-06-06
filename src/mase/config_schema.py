"""`config.json` 的 pydantic v2 校验层。

目标：
1. 在启动阶段发现拼写错误和必填字段缺失，而不是跑到第 250 道 LV-Eval 才失败。
2. 保持非破坏性：软问题发事件/返回 warning；只有缺少必需 agent、结构畸形等
   灾难性问题才在 strict 模式下抛错。
3. 记录 `model_interface` 实际读取的配置形状，避免贡献者从运行时错误反推 schema。

使用方式：`engine` 启动时调用 `validate_config_path()`；测试可以直接对 dict 调用
`validate_config()`。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .event_bus import get_bus

REQUIRED_AGENTS: tuple[str, ...] = ("router", "notetaker", "planner", "executor")


class ModeOverride(BaseModel):
    """`models.<agent>.modes.<mode_name>` 下的单个模式覆盖配置。"""

    model_config = ConfigDict(extra="allow")

    provider: str | None = None
    model_name: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    ollama_options: dict[str, Any] | None = None
    fallback_models: list[dict[str, Any]] | None = None


class AgentModelConfig(BaseModel):
    """`models.<agent>` 下的顶层 agent 配置块。"""

    model_config = ConfigDict(extra="allow")

    provider: str = Field(..., min_length=1, description="ollama | anthropic | openai | ...")
    model_name: str = Field(..., min_length=1)
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    ollama_options: dict[str, Any] | None = None
    modes: dict[str, ModeOverride] = Field(default_factory=dict)
    fallback_models: list[dict[str, Any]] | None = None


class ModelsBlock(BaseModel):
    """四个必需 agent 的配置容器。"""

    model_config = ConfigDict(extra="allow")

    router: AgentModelConfig
    notetaker: AgentModelConfig
    planner: AgentModelConfig
    executor: AgentModelConfig

    @field_validator("router", "notetaker", "planner", "executor")
    @classmethod
    def _agent_must_be_complete(cls, value: AgentModelConfig) -> AgentModelConfig:
        """每个必需 agent 至少要有 provider 和 model_name。"""
        if not value.provider or not value.model_name:
            raise ValueError("agent block requires both provider and model_name")
        return value


class MASEConfig(BaseModel):
    """顶层 `config.json` 形状；供应商私有字段通过 extra=allow 保留。"""

    model_config = ConfigDict(extra="allow")

    env_file: str | None = None
    models: ModelsBlock
    memory: dict[str, Any] = Field(default_factory=dict)
    orchestration: dict[str, Any] = Field(default_factory=dict)
    fallbacks: dict[str, Any] = Field(default_factory=dict)


class ConfigValidationError(Exception):
    """配置完全无法解析时抛出的硬错误。"""


def validate_config(raw: dict[str, Any], *, strict: bool = False) -> tuple[MASEConfig | None, list[str]]:
    """校验配置 dict。

    返回 `(parsed_or_None, warnings)`。

    - 成功：返回解析后的模型和软告警。
    - `strict=False` 失败：返回 `(None, [error_strings])`，调用方仍可用原始 dict 继续。
    - `strict=True` 失败：抛出 `ConfigValidationError`。
    """
    warnings: list[str] = []
    try:
        parsed = MASEConfig.model_validate(raw)
    except ValidationError as exc:
        messages = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
        if strict:
            raise ConfigValidationError("config validation failed:\n  - " + "\n  - ".join(messages)) from exc
        return None, messages
    # 软校验：提醒配置质量问题，但不阻断已有本地/云端 profile 运行。
    for agent in REQUIRED_AGENTS:
        block = getattr(parsed.models, agent)
        if block.provider == "ollama" and not (block.ollama_options or {}).get("num_ctx"):
            warnings.append(f"models.{agent}.ollama_options.num_ctx not set — relying on Ollama default 2048")
    return parsed, warnings


def validate_config_path(config_path: str | Path, *, strict: bool = False, emit_events: bool = True) -> tuple[MASEConfig | None, list[str]]:
    """读取并校验 `config_path`，可选把结果发布到 event bus。"""
    text = Path(config_path).read_text(encoding="utf-8")
    raw = json.loads(text)
    parsed, messages = validate_config(raw, strict=strict)
    if emit_events:
        bus = get_bus()
        if parsed is None:
            bus.publish(
                "mase.config.validation.failed",
                {"path": str(config_path), "errors": messages, "strict": strict},
            )
        elif messages:
            bus.publish(
                "mase.config.validation.warning",
                {"path": str(config_path), "warnings": messages},
            )
        else:
            bus.publish("mase.config.validation.ok", {"path": str(config_path)})
    return parsed, messages


__all__ = [
    "AgentModelConfig",
    "ConfigValidationError",
    "MASEConfig",
    "ModeOverride",
    "ModelsBlock",
    "REQUIRED_AGENTS",
    "validate_config",
    "validate_config_path",
]
