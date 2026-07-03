"""冲突覆盖决策(总纲 §4.4.2 默认优先级的机械化 v1)。

trust 阶梯即优先级序:human reviewed(E5)> 用户显式陈述(E5)> 可信文件(E4)
> 工具观测(E3)> 派生摘要(E2)> 单次推断(E1)。decision_score 九项全公式留 P2+。
"""
from __future__ import annotations

SUPERSEDE = "supersede"
QUARANTINE_NEW = "quarantine_new"


def resolve_conflict(new_trust: int, old_trust: int) -> str:
    """同键不同值时的覆盖决策。

    新证据信任不低于旧 → 时间性更新(supersede,版本链可回放,非静默丢失);
    新证据信任更低 → 显性冲突(新事实隔离 + conflicts_with 边,旧 active 不动)。
    """
    return SUPERSEDE if new_trust >= old_trust else QUARANTINE_NEW
