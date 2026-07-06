"""时漂压力基准的确定性场景生成(设计规范 2026-07-07,无随机、无系统时间)。

四个场景族 × 时间档位 t∈{0,7,30,90} 天 × 治理/退化两种记忆模式:
- update:同键 n 版知识更新链(n 随 index 变化),考"只用最新值、不漏旧值";
- conflict:高信任在前、低信任在后的同键冲突对(信任对随 index 变化),
  考"显式双陈列而非静默单边";
- ttl:tool_state 事实回灌 t 天前,考 TTL 生效边界(<7 天该在、≥7 天必须不在);
- unknown:查询从未入库的键,考"显性未知而非编造"。

退化模式(degraded)= 每版独立 scope 落库,全部保持 active——模拟"只追加、
无更新语义"的黑盒记忆,用于展示治理层的分离度;conflict/ttl 语义由治理层
承载,退化模式仅覆盖 update 与 conflict 两族。

case 定义完全由 index 推导(值取不互为子串的词表),manifest 哈希与时间无关。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

T_BUCKETS = (0, 7, 30, 90)
_WORDS = ("north", "south", "east", "west", "prime", "delta", "omega", "zenith")
_TRUST_PAIRS = ((4, 2), (3, 1), (5, 2), (4, 1))  # (先到高信任, 后到低信任)
_TOOL_TTL_DAYS = 7  # admission gate G5 对 tool_state 的默认 TTL


@dataclass(frozen=True)
class Scenario:
    """一条压力用例;offset_days 相对查询时刻(运行时回灌为过去时间)。"""

    case_id: str
    family: str
    mode: str  # governed | degraded
    t_days: int
    subject: str
    predicate: str
    versions: tuple[dict, ...]  # {value, offset_days, trust, claim_type}
    query_keywords: tuple[str, ...]
    expected: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON 序列化(manifest 与 results 共用)。"""
        return asdict(self)


def _value(case_index: int, version_index: int) -> str:
    word = _WORDS[(case_index + version_index) % len(_WORDS)]
    return f"{word}-{100 * (version_index + 1)}"


def _update_cases(per_family: int, t_days: int, mode: str) -> list[Scenario]:
    cases = []
    for i in range(per_family):
        chain = 3 + (i % 4)  # 链长 3..6,结构性变化
        versions = tuple(
            {
                "value": _value(i, v),
                "offset_days": t_days + (chain - v),  # 越新的版本离查询时刻越近
                "trust": 3,
                "claim_type": "project_fact",
            }
            for v in range(chain)
        )
        latest = versions[-1]["value"]
        cases.append(Scenario(
            case_id=f"update-{mode}-t{t_days}-{i:03d}",
            family="update", mode=mode, t_days=t_days,
            subject=f"user{i}", predicate=f"budget_amount_{i}",
            versions=versions,
            query_keywords=(f"budget_amount_{i}",),
            expected={
                "latest_value": latest,
                "stale_values": [v["value"] for v in versions[:-1]],
            },
        ))
    return cases


def _conflict_cases(per_family: int, t_days: int, mode: str) -> list[Scenario]:
    cases = []
    for i in range(per_family):
        high, low = _TRUST_PAIRS[i % len(_TRUST_PAIRS)]
        value_a, value_b = _value(i, 0), _value(i, 3)
        versions = (
            {"value": value_a, "offset_days": t_days + 2, "trust": high, "claim_type": "project_fact"},
            {"value": value_b, "offset_days": t_days + 1, "trust": low, "claim_type": "project_fact"},
        )
        cases.append(Scenario(
            case_id=f"conflict-{mode}-t{t_days}-{i:03d}",
            family="conflict", mode=mode, t_days=t_days,
            subject=f"vendor{i}", predicate=f"contract_owner_{i}",
            versions=versions,
            query_keywords=(f"contract_owner_{i}",),
            expected={"side_values": [value_a, value_b], "trusted_value": value_a},
        ))
    return cases


def _ttl_cases(per_family: int, t_days: int) -> list[Scenario]:
    cases = []
    for i in range(per_family):
        value = _value(i, 5)
        cases.append(Scenario(
            case_id=f"ttl-governed-t{t_days}-{i:03d}",
            family="ttl", mode="governed", t_days=t_days,
            subject=f"workspace{i}", predicate=f"open_file_{i}",
            versions=({"value": value, "offset_days": t_days, "trust": 3, "claim_type": "tool_state"},),
            query_keywords=(f"open_file_{i}",),
            expected={"value": value, "should_verify": t_days < _TOOL_TTL_DAYS},
        ))
    return cases


def _unknown_cases(per_family: int, t_days: int) -> list[Scenario]:
    cases = []
    for i in range(per_family):
        cases.append(Scenario(
            case_id=f"unknown-governed-t{t_days}-{i:03d}",
            family="unknown", mode="governed", t_days=t_days,
            subject=f"user{i}", predicate=f"present_key_{i}",
            versions=({"value": _value(i, 2), "offset_days": t_days, "trust": 3, "claim_type": "project_fact"},),
            query_keywords=(f"absent_key_{i}",),
            expected={"absent_keyword": f"absent_key_{i}"},
        ))
    return cases


def build_scenarios(per_family: int = 5) -> list[Scenario]:
    """全量场景,确定性排序;per_family 控制每 (族, t, 模式) 的结构变体数。"""
    scenarios: list[Scenario] = []
    for t_days in T_BUCKETS:
        for mode in ("governed", "degraded"):
            scenarios.extend(_update_cases(per_family, t_days, mode))
            scenarios.extend(_conflict_cases(per_family, t_days, mode))
        scenarios.extend(_ttl_cases(per_family, t_days))
        scenarios.extend(_unknown_cases(per_family, t_days))
    return scenarios


def scenarios_manifest_sha256(scenarios: list[Scenario]) -> str:
    """内容哈希(与时间无关):同参数双跑必须一致。"""
    payload = json.dumps([s.to_dict() for s in scenarios], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
