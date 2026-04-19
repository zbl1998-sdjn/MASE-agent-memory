"""Static marker token tuples used by mode/heat heuristics.

Centralised so that adding a new language or category of trigger words
does not force edits in `engine.py` or other consumer modules.
"""
from __future__ import annotations

ZH_REASONING_MARKERS: tuple[str, ...] = (
    "总共",
    "一共",
    "合计",
    "比较",
    "对比",
    "分析",
    "统计",
    "计算",
    "多少个",
    "多少次",
    "几次",
    "几天",
    "几周",
    "几小时",
    "先后",
)

EN_REASONING_MARKERS: tuple[str, ...] = (
    "how many",
    "how much",
    "how long",
    "count",
    "compare",
    "analysis",
    "analyze",
    "calculate",
    "total",
    "sum",
    "difference",
    "happened first",
    "happened last",
    "days between",
    "days had passed",
)

ZH_DISAMBIGUATION_MARKERS: tuple[str, ...] = ("是谁", "叫什么", "哪个", "哪一个", "分别是谁")
EN_DISAMBIGUATION_MARKERS: tuple[str, ...] = ("who", "which", "what name", "whose")
ZH_HOT_MEMORY_MARKERS: tuple[str, ...] = ("刚才", "刚刚", "最近", "今天", "今天早些时候", "方才")
EN_HOT_MEMORY_MARKERS: tuple[str, ...] = ("just now", "recently", "today", "earlier today", "moments ago")


def contains_any(text: str, markers: tuple[str, ...]) -> bool:
    """Case-insensitive substring containment check used across modules."""
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in markers)
