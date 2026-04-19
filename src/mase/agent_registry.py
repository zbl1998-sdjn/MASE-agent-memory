"""Agent registry — discoverable, pluggable agent factories.

Why this exists
---------------
The first version of MASE hard-coded the four built-in agents
(router / notetaker / planner / executor) inside ``engine.MASESystem.__init__``.
Every new agent kind (math, code, multimodal, retrieval, judge, ...) used to
require editing that class.  That is exactly the "god-class" pattern we just
broke up; we don't want to recreate it.

The registry replaces hard-coded ``self.foo_agent = FooAgent(...)`` with::

    @register_agent("router")
    def _make_router(model_interface, config_path):
        return RouterAgent(model_interface)

The engine then asks the registry for whatever agents are present.  Plug-ins
(including ones that live outside this package) only need to import the
registry and decorate their factory.

Design notes
------------
* Factories receive ``(model_interface, config_path)`` and return any object.
  The engine doesn't constrain the agent class — only that the public methods
  it calls exist.
* ``register_agent`` is idempotent for re-imports (Python module reloads):
  re-registering the same name silently replaces the previous factory rather
  than raising, which keeps notebook/dev workflows sane.
* ``required=True`` factories MUST resolve at engine startup; ``required=False``
  agents (future math/code/multimodal kinds) can be missing without breaking
  the core long-context / long-memory path.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

AgentFactory = Callable[[Any, "str | Path | None"], Any]


@dataclass(frozen=True)
class AgentSpec:
    name: str
    factory: AgentFactory
    required: bool = False
    description: str = ""


class AgentRegistry:
    """Process-wide registry of agent factories.

    Thread-safe.  Tests should call :meth:`snapshot` / :meth:`restore` instead
    of mutating the global instance directly so that parallel test workers do
    not leak registrations into one another.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._specs: dict[str, AgentSpec] = {}

    def register(
        self,
        name: str,
        factory: AgentFactory,
        *,
        required: bool = False,
        description: str = "",
    ) -> AgentSpec:
        if not name or not isinstance(name, str):
            raise ValueError(f"agent name must be a non-empty string, got {name!r}")
        spec = AgentSpec(name=name, factory=factory, required=required, description=description)
        with self._lock:
            self._specs[name] = spec
        return spec

    def unregister(self, name: str) -> None:
        with self._lock:
            self._specs.pop(name, None)

    def get(self, name: str) -> AgentSpec | None:
        with self._lock:
            return self._specs.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._specs)

    def required_names(self) -> list[str]:
        with self._lock:
            return sorted(name for name, spec in self._specs.items() if spec.required)

    def build_all(self, model_interface: Any, config_path: "str | Path | None") -> dict[str, Any]:
        """Instantiate every registered agent.

        Required agents propagate exceptions; optional ones are skipped with a
        ``None`` value so callers can detect them via ``agents.get(name)``.
        """
        with self._lock:
            specs = list(self._specs.values())
        instances: dict[str, Any] = {}
        for spec in specs:
            try:
                instances[spec.name] = spec.factory(model_interface, config_path)
            except Exception:
                if spec.required:
                    raise
                instances[spec.name] = None
        return instances

    def snapshot(self) -> dict[str, AgentSpec]:
        with self._lock:
            return dict(self._specs)

    def restore(self, snapshot: dict[str, AgentSpec]) -> None:
        with self._lock:
            self._specs = dict(snapshot)


_REGISTRY = AgentRegistry()


def register_agent(
    name: str,
    *,
    required: bool = False,
    description: str = "",
) -> Callable[[AgentFactory], AgentFactory]:
    """Decorator form — register an agent factory under ``name``.

    Usage::

        @register_agent("math", description="symbolic math agent")
        def _make_math(model_interface, config_path):
            return MathAgent(model_interface)
    """

    def _decorate(factory: AgentFactory) -> AgentFactory:
        _REGISTRY.register(name, factory, required=required, description=description)
        return factory

    return _decorate


def get_registry() -> AgentRegistry:
    return _REGISTRY


def register_builtin_agents() -> None:
    """Register the four built-in MASE agents.

    Imported lazily inside the function body so the registry module itself
    stays free of agent-class imports (and therefore safe to import from
    anywhere, including external plug-ins).
    """
    from .benchmark_notetaker import BenchmarkNotetaker
    from .planner_agent import PlannerAgent
    from .router import RouterAgent

    @register_agent("router", required=True, description="qwen2.5:0.5b heuristic router")
    def _make_router(model_interface: Any, config_path: Any) -> Any:
        del config_path
        return RouterAgent(model_interface)

    @register_agent("notetaker", required=True, description="FTS5 + co-occurrence rerank notetaker")
    def _make_notetaker(model_interface: Any, config_path: Any) -> Any:
        del model_interface
        return BenchmarkNotetaker(config_path)

    @register_agent("planner", required=True, description="Heuristic / model-backed planner")
    def _make_planner(model_interface: Any, config_path: Any) -> Any:
        del config_path
        return PlannerAgent(model_interface)


__all__ = [
    "AgentFactory",
    "AgentSpec",
    "AgentRegistry",
    "register_agent",
    "get_registry",
    "register_builtin_agents",
]
