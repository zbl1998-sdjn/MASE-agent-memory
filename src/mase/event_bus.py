"""事件总线：解耦 engine 生命周期事件的发布/订阅。

为什么需要它
------------
健壮性、可观测性、热切换能力都会关注相同的 engine 事件（route decided、
model call failed、executor finished、fact_sheet built 等）。把这些逻辑直接接进
``engine.MASESystem`` 会重新制造上帝类。

事件总线允许任意模块订阅 topic 并接收对应事件，而 engine 无需知道订阅者存在。

设计
----
* Topic 使用点分字符串，如 ``mase.route.decided``、``mase.executor.done``。
* 订阅者可监听精确 topic 或前缀。订阅 ``"mase"`` 会收到系统全部事件；
  订阅 ``"mase.model"`` 只收到模型相关事件。
* 发布是 **fire-and-forget**：订阅者异常会被捕获并缓存（可通过
  :meth:`drain_errors` 查看），避免坏 logger 崩掉 engine。
* 事件携带不可变 payload 映射和自动生成的 ``trace_id``，用于关联同一问题的
  router -> notetaker -> executor 链路。
* 仅同步分发。当前 engine 在单 Python 进程中运行，benchmark 需要确定性顺序；
  异步 fan-out 暂不在范围内。
"""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

EventHandler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    """一次已发布事件。"""

    topic: str
    payload: dict[str, Any]
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)


@dataclass
class _Subscription:
    pattern: str  # 精确 topic 或前缀：event.topic == pattern 或以 pattern + "." 开头。
    handler: EventHandler

    def matches(self, topic: str) -> bool:
        if self.pattern == topic:
            return True
        return topic.startswith(self.pattern + ".")


class EventBus:
    """进程级发布/订阅总线；线程安全，同步分发。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: list[_Subscription] = []
        self._errors: list[tuple[str, BaseException]] = []
        self._max_errors = 256

    # ---- 订阅管理 ----
    def subscribe(self, pattern: str, handler: EventHandler) -> Callable[[], None]:
        """注册订阅并返回取消订阅函数。"""
        if not pattern or not callable(handler):
            raise ValueError("subscribe requires a non-empty pattern and a callable handler")
        sub = _Subscription(pattern=pattern, handler=handler)
        with self._lock:
            self._subs.append(sub)

        def _unsubscribe() -> None:
            # 取消订阅是幂等的，重复调用不会抛错。
            with self._lock:
                try:
                    self._subs.remove(sub)
                except ValueError:
                    pass

        return _unsubscribe

    def unsubscribe_all(self, pattern: str | None = None) -> int:
        """取消全部订阅，或只取消某个 pattern 的订阅。"""
        with self._lock:
            if pattern is None:
                removed = len(self._subs)
                self._subs.clear()
                return removed
            keep = [s for s in self._subs if s.pattern != pattern]
            removed = len(self._subs) - len(keep)
            self._subs = keep
            return removed

    # ---- 发布 ----
    def publish(self, topic: str, payload: dict[str, Any] | None = None, trace_id: str | None = None) -> Event:
        """同步发布事件；订阅者异常只记录不传播。"""
        if not topic:
            raise ValueError("topic must be a non-empty string")
        event = Event(
            topic=topic,
            payload=dict(payload or {}),
            trace_id=trace_id or uuid.uuid4().hex,
        )
        with self._lock:
            handlers = [s.handler for s in self._subs if s.matches(topic)]
        for handler in handlers:
            try:
                handler(event)
            except BaseException as exc:  # noqa: BLE001 — never let observers crash the engine
                with self._lock:
                    # 只保留最近一段错误，避免长跑 benchmark 中错误队列无限增长。
                    self._errors.append((topic, exc))
                    if len(self._errors) > self._max_errors:
                        self._errors = self._errors[-self._max_errors :]
        return event

    # ---- 诊断 ----
    def subscribers(self) -> list[str]:
        """返回当前订阅 pattern 列表。"""
        with self._lock:
            return [s.pattern for s in self._subs]

    def drain_errors(self) -> list[tuple[str, BaseException]]:
        """取出并清空订阅者异常缓存。"""
        with self._lock:
            errors = list(self._errors)
            self._errors.clear()
            return errors


_BUS = EventBus()


def get_bus() -> EventBus:
    return _BUS


def publish(topic: str, payload: dict[str, Any] | None = None, trace_id: str | None = None) -> Event:
    return _BUS.publish(topic, payload, trace_id)


def subscribe(pattern: str, handler: EventHandler) -> Callable[[], None]:
    return _BUS.subscribe(pattern, handler)


# ---- 规范 topic 常量：让订阅者和 engine 对齐事件名 ----
class Topics:
    ROUTE_DECIDED = "mase.route.decided"
    NOTETAKER_SEARCH_DONE = "mase.notetaker.search.done"
    NOTETAKER_FACT_SHEET_DONE = "mase.notetaker.fact_sheet.done"
    EXECUTOR_CALL_START = "mase.executor.call.start"
    EXECUTOR_CALL_DONE = "mase.executor.call.done"
    EXECUTOR_VERIFY_DONE = "mase.executor.verify.done"
    RUN_DONE = "mase.run.done"
    MODEL_CALL_FAILED = "mase.model.call.failed"
    MODEL_FALLBACK_USED = "mase.model.fallback.used"


__all__ = [
    "Event",
    "EventBus",
    "EventHandler",
    "Topics",
    "get_bus",
    "publish",
    "subscribe",
]
