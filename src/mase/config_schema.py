"""Config schema — pydantic v2 validation for ``config.json``.

Goals
-----
1. Catch typos and missing fields at startup, not at the 250th LV-Eval
   question.
2. Be **non-breaking**: validation logs warnings and emits an event for soft
   issues; only catastrophic problems (missing required agent, malformed
   shape) raise.  Real configs always have legitimate vendor-specific extras
   so every model uses ``extra="allow"``.
3. Document the actual shape that ``model_interface`` reads, so future
   contributors don't have to reverse-engineer it from runtime errors.

Usage
-----
The engine calls :func:`validate_config_path` at startup.  Tests can call
:func:`validate_config` directly with a dict.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .event_bus import get_bus

REQUIRED_AGENTS: tuple[str, ...] = ("router", "notetaker", "planner", "executor")


class ModeOverride(BaseModel):
    """A per-mode override under ``models.<agent>.modes.<mode_name>``."""

    model_config = ConfigDict(extra="allow")

    provider: str | None = None
    model_name: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    ollama_options: dict[str, Any] | None = None
    fallback_models: list[dict[str, Any]] | None = None


class AgentModelConfig(BaseModel):
    """Top-level agent block under ``models.<agent>``."""

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
    model_config = ConfigDict(extra="allow")

    router: AgentModelConfig
    notetaker: AgentModelConfig
    planner: AgentModelConfig
    executor: AgentModelConfig

    @field_validator("router", "notetaker", "planner", "executor")
    @classmethod
    def _agent_must_be_complete(cls, value: AgentModelConfig) -> AgentModelConfig:
        if not value.provider or not value.model_name:
            raise ValueError("agent block requires both provider and model_name")
        return value


class MASEConfig(BaseModel):
    """Top-level ``config.json`` shape."""

    model_config = ConfigDict(extra="allow")

    env_file: str | None = None
    models: ModelsBlock
    memory: dict[str, Any] = Field(default_factory=dict)
    orchestration: dict[str, Any] = Field(default_factory=dict)
    fallbacks: dict[str, Any] = Field(default_factory=dict)


class ConfigValidationError(Exception):
    """Raised when the config cannot be parsed at all (unrecoverable)."""


def validate_config(raw: dict[str, Any], *, strict: bool = False) -> tuple[MASEConfig | None, list[str]]:
    """Validate a config dict.

    Returns ``(parsed_or_None, warnings)``.

    - On success: returns the parsed model and any soft warnings.
    - On failure with ``strict=False`` (default): returns ``(None, [error_strings])``
      so callers can keep running on the raw dict.
    - On failure with ``strict=True``: raises :class:`ConfigValidationError`.
    """
    warnings: list[str] = []
    try:
        parsed = MASEConfig.model_validate(raw)
    except ValidationError as exc:
        messages = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
        if strict:
            raise ConfigValidationError("config validation failed:\n  - " + "\n  - ".join(messages)) from exc
        return None, messages
    # Soft checks that should warn, not crash.
    for agent in REQUIRED_AGENTS:
        block = getattr(parsed.models, agent)
        if block.provider == "ollama" and not (block.ollama_options or {}).get("num_ctx"):
            warnings.append(f"models.{agent}.ollama_options.num_ctx not set — relying on Ollama default 2048")
    return parsed, warnings


def validate_config_path(config_path: str | Path, *, strict: bool = False, emit_events: bool = True) -> tuple[MASEConfig | None, list[str]]:
    """Load and validate the config at ``config_path``."""
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
