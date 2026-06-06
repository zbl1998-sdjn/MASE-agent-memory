"""Circuit breaker：在健康跟踪器之上暴露 ``open`` 状态。

健康跟踪器已经实现连续失败 N 次后的 cooldown，从语义上就是半开熔断。本模块用
标准 breaker 词汇暴露同一概念，便于调用方和 metrics label 明确表达。

状态：

* ``closed``  — calls flow normally
* ``open``    — calls would fail-fast (we still let one through to detect
                recovery; that's the standard half-open trick)
* ``half_open`` — implicit; same condition as ``open`` past the cooldown
                  window.

为什么不引入 ``pybreaker``？理由和 structured logger 类似：项目已有可用 cooldown。
再叠 pybreaker 会为每个 provider/model 增加进程级锁和第二套事实源。本 wrapper
直接复用 tracker 状态即可。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .health_tracker import CandidateHealthTracker, get_tracker


@dataclass
class BreakerState:
    """单个 provider/model 的 breaker 展示状态。"""

    provider: str
    model: str
    state: str  # "closed" | "open" | "half_open"
    consecutive_failures: int
    seconds_until_retry: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "seconds_until_retry": round(self.seconds_until_retry, 1),
        }


def state_for(provider: str, model: str, tracker: CandidateHealthTracker | None = None) -> BreakerState:
    """根据健康跟踪器状态计算单个候选的 breaker 状态。"""
    tracker = tracker or get_tracker()
    snap = {(h["provider"], h["model"]): h for h in tracker.snapshot()}
    health = snap.get((provider, model))
    if health is None or health["consecutive_failures"] < tracker.cooldown_failures:
        # 未见候选或失败未达阈值时保持 closed。
        return BreakerState(provider=provider, model=model, state="closed",
                            consecutive_failures=health["consecutive_failures"] if health else 0,
                            seconds_until_retry=0.0)
    elapsed = time.time() - tracker._healths[(provider, model)].last_failure_at  # noqa: SLF001
    seconds_until_retry = max(0.0, tracker.cooldown_seconds - elapsed)
    if seconds_until_retry > 0:
        # cooldown 窗口内为 open，调用层可选择 fail-fast 或放到最后尝试。
        return BreakerState(
            provider=provider,
            model=model,
            state="open",
            consecutive_failures=health["consecutive_failures"],
            seconds_until_retry=seconds_until_retry,
        )
    return BreakerState(
        # cooldown 已过但连续失败仍在，展示为 half_open，等待下一次探测调用。
        provider=provider,
        model=model,
        state="half_open",
        consecutive_failures=health["consecutive_failures"],
        seconds_until_retry=0.0,
    )


def snapshot(tracker: CandidateHealthTracker | None = None) -> list[dict[str, Any]]:
    """返回所有已见候选的 breaker 状态快照。"""
    tracker = tracker or get_tracker()
    return [
        state_for(h["provider"], h["model"], tracker=tracker).to_dict()
        for h in tracker.snapshot()
    ]


__all__ = ["BreakerState", "snapshot", "state_for"]
