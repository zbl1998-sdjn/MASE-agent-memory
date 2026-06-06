"""结构化日志：订阅事件总线并输出 JSON Lines。

为什么不依赖 ``structlog``？项目已经固定了 ``httpx``、``ollama``、``pydantic``
等依赖；仅为把 dict 格式化成 JSON 再加一个依赖过重。标准库 ``logging`` 加一个
小型 JSON formatter 足够，并保持 V1 的安装体积。

做什么
------
导入或调用 ``configure()`` 时，会在事件总线上订阅 ``"mase"`` pattern，也就是
所有 engine 事件。每个事件会输出为一行 JSON，默认写到 stderr，形状如下::

    {"ts": 1700000000.123, "trace_id": "abc...", "topic": "mase.executor.call.done",
     "executor_mode": "grounded_long_context", "answer_chars": 213}

操作者可以 ``tail -f mase.log``，并直接接入 Loki、Datadog、ELK 等日志流水线。
``trace_id`` 关联同一次请求的 router -> notetaker -> executor，对区分
LongMemEval 失败中的 pipeline-routing 问题和模型问题很有价值。
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Any

from .event_bus import Event, get_bus

_LOCK = threading.Lock()
_INSTALLED: dict[str, Any] = {"unsubscribe": None, "logger": None}


def _format_event(event: Event) -> str:
    """把 Event 转成单行 JSON 字符串。"""
    record: dict[str, Any] = {
        "ts": round(event.timestamp, 3),
        "trace_id": event.trace_id,
        "topic": event.topic,
    }
    for key, value in event.payload.items():
        # payload 必须可 JSON 序列化；不可序列化对象退回 repr。
        try:
            json.dumps(value)
            record[key] = value
        except TypeError:
            record[key] = repr(value)
    return json.dumps(record, ensure_ascii=False)


def configure(
    *,
    stream: Any | None = None,
    level: int = logging.INFO,
    pattern: str = "mase",
    logger_name: str = "mase",
) -> logging.Logger:
    """安装或重装结构化日志订阅。

    重复调用会替换旧订阅，避免 reload-config 后每个事件被重复输出。
    """
    with _LOCK:
        previous = _INSTALLED.get("unsubscribe")
        if callable(previous):
            try:
                previous()
            except Exception:
                pass

        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        # 用户已经接入 handler 时不重复添加。
        if not logger.handlers:
            handler = logging.StreamHandler(stream or sys.stderr)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            logger.propagate = False

        def _emit(event: Event) -> None:
            try:
                logger.info(_format_event(event))
            except Exception:
                # 日志输出必须 best-effort，不能反向影响事件发布链路。
                pass

        unsubscribe = get_bus().subscribe(pattern, _emit)
        _INSTALLED["unsubscribe"] = unsubscribe
        _INSTALLED["logger"] = logger
        return logger


def get_logger(name: str = "mase") -> logging.Logger:
    """返回指定名称的标准库 logger。"""
    return logging.getLogger(name)


__all__ = ["configure", "get_logger"]
