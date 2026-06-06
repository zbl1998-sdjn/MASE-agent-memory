"""进程内指标：从事件总线聚合 counter 和延迟均值。

为什么不直接引入 Prometheus client？
-----------------------------------
本项目主要是本地运行并产出 JSON 报告的 benchmark 工具，引入第三方 HTTP exporter
收益有限。这里通过以下方式暴露同一份数据：

* ``Metrics.snapshot()`` — JSON dict, easy to embed in benchmark reports
* ``mase metrics`` CLI subcommand — print snapshot
* ``Metrics.format_prometheus()`` — text-format Prometheus exposition that
  any external scrape can serve, if you want one.

Counter 由 event topic 自动派生，新增事件 topic 会自然生成新 counter，不需要为
每种事件改本模块。
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

from .event_bus import Event, get_bus
from .health_tracker import get_tracker


class Metrics:
    """订阅事件总线并维护进程内指标快照。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latency_sum_ms: dict[str, float] = defaultdict(float)
        self._latency_count: dict[str, int] = defaultdict(int)
        self._unsubscribe: Any = None

    def install(self) -> None:
        """安装事件订阅；重复调用保持幂等。"""
        with self._lock:
            if self._unsubscribe is not None:
                return
            self._unsubscribe = get_bus().subscribe("mase", self._on_event)

    def uninstall(self) -> None:
        """卸载事件订阅，主要给测试和热重载使用。"""
        with self._lock:
            if self._unsubscribe is not None:
                try:
                    self._unsubscribe()
                except Exception:
                    pass
                self._unsubscribe = None

    def _on_event(self, event: Event) -> None:
        """事件回调：累加 topic counter 和 latency 均值所需分子/分母。"""
        topic = event.topic
        with self._lock:
            self._counters[topic] += 1
            latency = event.payload.get("latency_ms")
            if isinstance(latency, int | float) and latency > 0:
                self._latency_sum_ms[topic] += float(latency)
                self._latency_count[topic] += 1

    def snapshot(self) -> dict[str, Any]:
        """返回 JSON 可序列化的指标快照。"""
        with self._lock:
            counters = dict(self._counters)
            latencies = {
                topic: round(self._latency_sum_ms[topic] / self._latency_count[topic], 2)
                for topic in self._latency_count
                if self._latency_count[topic] > 0
            }
        return {
            "event_counters": counters,
            "latency_ms_avg": latencies,
            "candidate_health": get_tracker().snapshot(),
        }

    def reset(self) -> None:
        """清空进程内 counter/latency。"""
        with self._lock:
            self._counters.clear()
            self._latency_sum_ms.clear()
            self._latency_count.clear()

    def format_prometheus(self) -> str:
        """输出 Prometheus text exposition 格式。"""
        snap = self.snapshot()
        lines: list[str] = []
        for topic, count in sorted(snap["event_counters"].items()):
            metric = "mase_events_total{topic=\"%s\"} %d" % (topic, count)
            lines.append(metric)
        for topic, avg in sorted(snap["latency_ms_avg"].items()):
            lines.append("mase_event_latency_ms_avg{topic=\"%s\"} %.2f" % (topic, avg))
        for h in snap["candidate_health"]:
            labels = "provider=\"%s\",model=\"%s\"" % (h["provider"], h["model"])
            lines.append("mase_candidate_success_rate{%s} %.4f" % (labels, h["success_rate"]))
            lines.append("mase_candidate_calls_total{%s} %d" % (labels, h["total_calls"]))
            lines.append("mase_candidate_failures_total{%s} %d" % (labels, h["total_failures"]))
        return "\n".join(lines) + "\n"


_METRICS = Metrics()
_METRICS.install()


def get_metrics() -> Metrics:
    """返回进程级 Metrics 单例。"""
    return _METRICS


__all__ = ["Metrics", "get_metrics"]
