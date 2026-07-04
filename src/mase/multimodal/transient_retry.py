"""瞬时基础设施错误重试(GPU 高压下 ollama 偶发 CUDA/5xx,整例白丢太贵)。

只对"瞬时 infra"类错误(CUDA error / server 5xx)重试一次并留 warning;
业务/配置错误原样抛。这是抽取管线容错(生产同样需要),不是评测按例重试
——评测 runner 的单次口径不变,重试发生与否都会在 warnings 里留痕。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_TRANSIENT_MARKERS = ("cuda error", "status code: 500", "status code: 502", "status code: 503")


def is_transient_infra_error(exc: BaseException) -> bool:
    """CUDA 崩溃与 server 5xx 视为瞬时(KEEP_ALIVE=0 下重调会重载模型,常可自愈)。"""
    text = str(exc).casefold()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def call_with_transient_retry(
    fn: Callable[[], T],
    *,
    warnings: list[str],
    sleep_seconds: float = 3.0,
) -> T:
    """执行 fn;瞬时 infra 错误等待后重试一次(留痕),其余异常原样抛。"""
    try:
        return fn()
    except Exception as exc:
        if not is_transient_infra_error(exc):
            raise
        warnings.append(f"transient_infra_retry: {type(exc).__name__}: {str(exc)[:120]}")
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        return fn()
