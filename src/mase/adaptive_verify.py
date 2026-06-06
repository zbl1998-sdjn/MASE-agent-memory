"""自适应 verifier 深度策略。

这是可插拔的纯决策模块，根据召回结果选择三种 verifier 深度之一：

    - "skip"   : retrieval is high-confidence and dominant; no cloud verifier
    - "single" : medium confidence; current single-verifier chain (kimi-k2.5)
    - "dual"   : low confidence or hard qtype; dual-verifier vote for precision

模块不做 I/O。默认阈值面向 LongMemEval 调过，可通过环境变量覆盖，便于消融实验
不改代码直接扫参数。

是否启用由调用点的 ``MASE_ADAPTIVE_VERIFY=1`` 控制；本模块本身始终可安全导入和
调用。调用方不接入时，既有 single-verifier 链路不变。
"""
from __future__ import annotations

import os
from typing import Literal

Decision = Literal["skip", "single", "dual"]

# LME 中经验上受益于 dual-verifier 投票的题型：多会话综合和时间推理是历史弱点。
HARD_QTYPES: frozenset[str] = frozenset({"multi-session", "temporal-reasoning"})

DEFAULT_SKIP_THRESHOLD = 0.85
DEFAULT_DUAL_THRESHOLD = 0.5
DEFAULT_DOMINANCE_GAP = 0.2


def _env_float(name: str, default: float) -> float:
    """读取浮点环境变量，非法值回退默认。"""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class AdaptiveVerifyPolicy:
    """纯决策策略：召回信号 -> verifier 深度。

    ``skip_threshold`` 控制跳过 verifier 所需 top-1 分数，``dual_threshold``
    控制进入双 verifier 的低分阈值，``dominance_gap`` 防止多个候选接近时误跳过。
    """

    def __init__(
        self,
        skip_threshold: float | None = None,
        dual_threshold: float | None = None,
        dominance_gap: float | None = None,
    ) -> None:
        self.skip_threshold = (
            skip_threshold
            if skip_threshold is not None
            else _env_float("MASE_VERIFY_SKIP_THRESHOLD", DEFAULT_SKIP_THRESHOLD)
        )
        self.dual_threshold = (
            dual_threshold
            if dual_threshold is not None
            else _env_float("MASE_VERIFY_DUAL_THRESHOLD", DEFAULT_DUAL_THRESHOLD)
        )
        self.dominance_gap = (
            dominance_gap
            if dominance_gap is not None
            else _env_float("MASE_VERIFY_DOMINANCE_GAP", DEFAULT_DOMINANCE_GAP)
        )

    @staticmethod
    def _candidate_score(c: object) -> float | None:
        """从候选 dict 中读取可比较分数。"""
        if isinstance(c, dict):
            for key in ("score", "similarity", "rerank_score", "confidence"):
                v = c.get(key)
                if isinstance(v, int | float):
                    return float(v)
        return None

    def _top_gap(self, candidates: list[dict]) -> float:
        if not candidates or len(candidates) < 2:
            return float("inf")  # 单候选天然 dominant。
        scores = [s for s in (self._candidate_score(c) for c in candidates) if s is not None]
        if len(scores) < 2:
            return float("inf")
        scores.sort(reverse=True)
        return scores[0] - scores[1]

    def decide(
        self,
        retrieval_score: float,
        candidates: list[dict],
        qtype: str | None = None,
    ) -> Decision:
        """把 (score, candidates, qtype) 映射为 verifier 深度。

        hard qtype 无论分数如何都升级为 "dual"；多会话/时间题的精度收益高于
        额外 verifier 调用成本。
        """
        if qtype in HARD_QTYPES:
            return "dual"

        try:
            score = float(retrieval_score)
        except (TypeError, ValueError):
            return "single"

        if score < self.dual_threshold:
            return "dual"

        if score >= self.skip_threshold and self._top_gap(candidates) > self.dominance_gap:
            return "skip"

        return "single"


__all__ = ["AdaptiveVerifyPolicy", "Decision", "HARD_QTYPES"]
