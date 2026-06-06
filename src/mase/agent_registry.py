"""Agent 注册表：可发现、可插拔的 agent 工厂。

为什么需要它
------------
MASE 早期版本把四个内建 agent（router/notetaker/planner/executor）硬编码在
``engine.MASESystem.__init__`` 里。每增加一种 agent（math/code/multimodal/
retrieval/judge/...）都要改这个类，这正是刚拆掉的上帝类模式，不能再重建。

注册表把硬编码的 ``self.foo_agent = FooAgent(...)`` 替换为::

    @register_agent("router")
    def _make_router(model_interface, config_path):
        return RouterAgent(model_interface)

engine 只向注册表索取已注册 agent。插件（包括包外插件）只需导入注册表并装饰
自己的工厂函数。

设计说明
--------
* 工厂接收 ``(model_interface, config_path)``，返回任意对象。engine 不约束类，
  只要求调用到的公开方法存在。
* ``register_agent`` 对重复导入幂等：同名重新注册会静默替换旧工厂，便于
  notebook/dev reload 工作流。
* ``required=True`` 的工厂必须在 engine 启动时可解析；``required=False`` 的
  未来 agent 可以缺失，不破坏核心长上下文/长记忆路径。
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AgentFactory = Callable[[Any, "str | Path | None"], Any]


@dataclass(frozen=True)
class AgentSpec:
    """单个 agent 工厂的注册元数据。"""

    name: str
    factory: AgentFactory
    required: bool = False
    description: str = ""


class AgentRegistry:
    """进程级 agent 工厂注册表。

    线程安全。测试应使用 :meth:`snapshot` / :meth:`restore`，避免直接改全局实例
    导致并行测试 worker 互相泄漏注册项。
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

    def build_all(self, model_interface: Any, config_path: str | Path | None) -> dict[str, Any]:
        """实例化所有已注册 agent。

        必需 agent 的异常直接抛出；可选 agent 失败时写入 ``None``，调用方可通过
        ``agents.get(name)`` 判断缺失。
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
    """装饰器形式：把 agent 工厂注册到 ``name``。

    用法::

        @register_agent("math", description="symbolic math agent")
        def _make_math(model_interface, config_path):
            return MathAgent(model_interface)
    """

    def _decorate(factory: AgentFactory) -> AgentFactory:
        _REGISTRY.register(name, factory, required=required, description=description)
        return factory

    return _decorate


def get_registry() -> AgentRegistry:
    """返回进程级注册表。"""
    return _REGISTRY


def register_builtin_agents() -> None:
    """注册 MASE 内建 agent。

    具体 agent 类在函数体内懒导入，使注册表模块本身不携带 agent-class 导入副作用，
    因而外部插件也可以安全导入。
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
