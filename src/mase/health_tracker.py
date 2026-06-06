"""候选模型健康跟踪器：按健康度、成本和延迟调整 fallback 顺序。

为什么需要它
------------
``model_interface._iter_model_candidates`` 会按固定配置顺序返回候选。某个云端
模型不可用时，如果每次仍先试它，就会反复浪费等待时间。进程内健康跟踪器可以：

* 学习当前健康候选
* 下次调用时优先健康候选
* 连续失败 N 次后进入 cooldown，避免持续打不可用端点
* 用延迟和可选 token 成本打破平局
* 始终保留至少一个本地 fallback 作为最后手段

跟踪器是进程级单例、线程安全，并且 **绝不让调用方崩溃**：所有操作都是
best-effort。

它接入 :mod:`event_bus`，让 metrics、structured log 等观察者看到同一组结果。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .event_bus import get_bus

# EWMA_ALPHA 控制新样本对历史的覆盖速度；越大越快响应。0.3 在稳定与响应之间折中：
# 一次失败会把满分候选从 1.000 拉到 0.700，足够降权，但不直接冷却。
_EWMA_ALPHA = 0.3
_DEFAULT_COOLDOWN_FAILURES = 3
_DEFAULT_COOLDOWN_SECONDS = 30.0
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "llama_cpp", "llamacpp", "local"})


@dataclass
class CandidateHealth:
    """单个 provider/model 的运行时健康状态。"""

    provider: str
    model: str
    success_rate: float = 1.0
    latency_ms_ewma: float = 0.0
    consecutive_failures: int = 0
    last_failure_at: float = 0.0
    last_success_at: float = 0.0
    total_calls: int = 0
    total_failures: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.model)

    def is_in_cooldown(self, now: float, cooldown_failures: int, cooldown_seconds: float) -> bool:
        """判断候选是否仍处于失败冷却窗口。"""
        if self.consecutive_failures < cooldown_failures:
            return False
        return (now - self.last_failure_at) < cooldown_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "success_rate": round(self.success_rate, 4),
            "latency_ms_ewma": round(self.latency_ms_ewma, 1),
            "consecutive_failures": self.consecutive_failures,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
        }


class CandidateHealthTracker:
    """进程内健康跟踪器，负责记录结果并重排候选列表。"""

    def __init__(
        self,
        cooldown_failures: int = _DEFAULT_COOLDOWN_FAILURES,
        cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self.cooldown_failures = cooldown_failures
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.RLock()
        self._healths: dict[tuple[str, str], CandidateHealth] = {}

    # ---- 结果记录 ----
    def _get(self, provider: str, model: str) -> CandidateHealth:
        """获取或创建候选健康记录。"""
        key = (provider, model)
        health = self._healths.get(key)
        if health is None:
            health = CandidateHealth(provider=provider, model=model)
            self._healths[key] = health
        return health

    def record_success(self, provider: str, model: str, latency_ms: float = 0.0) -> None:
        """记录一次成功调用，并发布健康事件。"""
        with self._lock:
            health = self._get(provider, model)
            health.total_calls += 1
            health.success_rate = (1 - _EWMA_ALPHA) * health.success_rate + _EWMA_ALPHA * 1.0
            if latency_ms > 0:
                if health.latency_ms_ewma == 0:
                    health.latency_ms_ewma = latency_ms
                else:
                    health.latency_ms_ewma = (1 - _EWMA_ALPHA) * health.latency_ms_ewma + _EWMA_ALPHA * latency_ms
            health.consecutive_failures = 0
            health.last_success_at = time.time()
        get_bus().publish("mase.health.success", {"provider": provider, "model": model, "latency_ms": latency_ms})

    def record_failure(self, provider: str, model: str, error: str = "") -> None:
        """记录一次失败调用，并在达到阈值后标记 cooldown。"""
        with self._lock:
            health = self._get(provider, model)
            health.total_calls += 1
            health.total_failures += 1
            health.success_rate = (1 - _EWMA_ALPHA) * health.success_rate + _EWMA_ALPHA * 0.0
            health.consecutive_failures += 1
            health.last_failure_at = time.time()
            in_cooldown = health.is_in_cooldown(health.last_failure_at, self.cooldown_failures, self.cooldown_seconds)
        get_bus().publish(
            "mase.health.failure",
            {"provider": provider, "model": model, "error": error[:240], "in_cooldown": in_cooldown},
        )

    # ---- 候选排序 ----
    def score(self, provider: str, model: str, cost_per_1k: float = 0.0) -> float:
        """分数越高越优先，用于降序排序。"""
        with self._lock:
            health = self._healths.get((provider, model))
        if health is None:
            return 1.0  # 未见候选保持中性偏正，避免新候选永远排不上来。
        # 成功率占主导；慢延迟和成本只做小惩罚。延迟惩罚封顶约 0.2，
        # 保证“慢但可用”仍优于“快但失败”。
        latency_penalty = min(0.2, health.latency_ms_ewma / 60_000.0)
        cost_penalty = min(0.1, cost_per_1k / 50.0) if cost_per_1k > 0 else 0.0
        return health.success_rate - latency_penalty - cost_penalty

    def sort_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        prefer_local: bool = False,
    ) -> list[dict[str, Any]]:
        """按健康分重排候选，并在同分时保留原始顺序偏好。

        规则：
        1. 不删除任何候选，所有候选仍可被尝试。
        2. cooldown 候选降到末尾，作为其它都失败后的最后选择。
        3. ``prefer_local`` 参数目前保留给调用层策略，当前排序只按健康分与原序。
        """
        now = time.time()
        with self._lock:
            scored: list[tuple[float, int, dict[str, Any]]] = []
            for index, candidate in enumerate(candidates):
                provider = str(candidate.get("provider") or "")
                model = str(candidate.get("model_name") or "")
                cost = float(candidate.get("cost_per_1k_tokens") or 0.0)
                base = self.score(provider, model, cost_per_1k=cost)
                health = self._healths.get((provider, model))
                cooldown_penalty = 0.0
                if health is not None and health.is_in_cooldown(now, self.cooldown_failures, self.cooldown_seconds):
                    cooldown_penalty = 1.0
                scored.append((base - cooldown_penalty, index, candidate))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [item[2] for item in scored]

    # ---- 状态查看 ----
    def snapshot(self) -> list[dict[str, Any]]:
        """返回所有候选健康状态的快照。"""
        with self._lock:
            return [h.to_dict() for h in self._healths.values()]

    def reset(self) -> None:
        """清空进程内健康状态，主要给测试/热重载使用。"""
        with self._lock:
            self._healths.clear()


_TRACKER = CandidateHealthTracker()


def get_tracker() -> CandidateHealthTracker:
    """返回进程级健康跟踪器。"""
    return _TRACKER


def is_local_provider(provider: str) -> bool:
    """判断 provider 是否属于本地 fallback 集合。"""
    return str(provider or "").lower() in _LOCAL_PROVIDERS


__all__ = [
    "CandidateHealth",
    "CandidateHealthTracker",
    "get_tracker",
    "is_local_provider",
]
