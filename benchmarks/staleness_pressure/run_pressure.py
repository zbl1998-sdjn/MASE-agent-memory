"""时漂压力基准跑分器:治理 vs 退化记忆的 staleness 分离度(全机械判分)。

每个 case 独立 SQLite:按场景回灌事实(observed_at = 现在 - offset_days),
用 compile_evidence_pack(P2 白盒召回+编译)取证据包,直接对 pack 判分——
不经过任何 LLM,分数完全可复现。

用法:
    python -X utf8 benchmarks/staleness_pressure/run_pressure.py [--per-family N] [--out-root DIR]
产物:<out_root>/staleness_pressure_<stamp>/{results.json}
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for _p in (_REPO / "src", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from generate_scenarios import (  # noqa: E402
    Scenario,
    build_scenarios,
    scenarios_manifest_sha256,
)


def _ts(now: datetime, offset_days: float) -> str:
    return (now - timedelta(days=offset_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_case(scenario: Scenario, db_path: Path, now: datetime) -> None:
    """按模式回灌版本:governed 走同键 supersession;degraded 每版独立 scope(只追加)。"""
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    for index, version in enumerate(scenario.versions):
        qualifiers = None
        if scenario.mode == "degraded":
            qualifiers = {"scope": f"v{index}"}  # 独立 scope=无更新语义,全部保持 active
        observed = _ts(now, float(version["offset_days"]))
        source = f"记录:{scenario.predicate} 更新为 {version['value']},登记于 {observed}。"
        propose_fact(
            FactContract(
                fact_id=new_fact_id(),
                entity_id=f"case:{scenario.subject}",
                claim_type=str(version["claim_type"]),
                subject=scenario.subject,
                predicate=scenario.predicate,
                object_value=str(version["value"]),
                confidence=0.9,
                observed_at=observed,
                qualifiers=qualifiers,
            ),
            str(version["value"]),
            source_type="chat",
            source_id=f"{scenario.case_id}:{index}",
            trust_level=int(version["trust"]),
            source_full_text=source,
            db_path=db_path,
        )


def score_case(scenario: Scenario, pack: Any) -> dict[str, Any]:
    """对证据包机械判分;返回该 case 的维度布尔值。"""
    verified_claims = [str(v.get("claim", "")) for v in pack.verified]
    dims: dict[str, Any] = {}
    if scenario.family == "update":
        latest = scenario.expected["latest_value"]
        stale = scenario.expected["stale_values"]
        dims["update_adopted"] = any(latest in c for c in verified_claims) and not any(
            s in c for s in stale for c in verified_claims
        )
        dims["stale_leak"] = any(s in c for s in stale for c in verified_claims)
    elif scenario.family == "conflict":
        value_a, value_b = scenario.expected["side_values"]
        side_claims = [
            str(side.get("claim", ""))
            for conflict in pack.conflicts
            for side in conflict.get("sides", [])
        ]
        dims["conflict_reported"] = any(value_a in c for c in side_claims) and any(
            value_b in c for c in side_claims
        )
        dims["stale_leak"] = any(
            scenario.expected["side_values"][1] in c for c in verified_claims
        )  # 低信任值被当已验证事实注入 = 单边采信泄漏
    elif scenario.family == "ttl":
        present = any(scenario.expected["value"] in c for c in verified_claims)
        dims["ttl_correct"] = present == bool(scenario.expected["should_verify"])
        dims["stale_leak"] = present and not scenario.expected["should_verify"]
    elif scenario.family == "unknown":
        keyword = scenario.expected["absent_keyword"]
        dims["unknown_honest"] = any(keyword in u for u in pack.unknowns)
        dims["stale_leak"] = False
    return dims


def run_case(scenario: Scenario, work_root: Path, now: datetime) -> dict[str, Any]:
    from mase.governance.evidence_pack import compile_evidence_pack

    case_dir = work_root / scenario.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    db_path = case_dir / "facts.db"
    seed_case(scenario, db_path, now)
    pack = compile_evidence_pack(
        question=f"当前 {scenario.predicate} 是什么?",
        keywords=list(scenario.query_keywords),
        db_path=db_path,
    )
    return score_case(scenario, pack)


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """按 (family, mode) 与 (family, mode, t) 聚合各维度通过率。"""
    def _bucket(items: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {"cases": len(items)}
        keys = {k for item in items for k in item["dims"]}
        for key in sorted(keys):
            values = [bool(item["dims"][key]) for item in items if key in item["dims"]]
            if values:
                out[f"{key}_rate"] = round(sum(values) / len(values), 4)
        return out

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(f"{row['family']}/{row['mode']}", []).append(row)
        groups.setdefault(f"{row['family']}/{row['mode']}/t{row['t_days']}", []).append(row)
    return {name: _bucket(items) for name, items in sorted(groups.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description="Staleness pressure benchmark (mechanical)")
    parser.add_argument("--per-family", type=int, default=5)
    parser.add_argument("--out-root", default="E:/MASE-runs/eval_runs")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    scenarios = build_scenarios(per_family=args.per_family)
    manifest = scenarios_manifest_sha256(scenarios)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_root).resolve() / f"staleness_pressure_{stamp}"
    work = out_dir / "work"

    rows: list[dict[str, Any]] = []
    for i, scenario in enumerate(scenarios, 1):
        dims = run_case(scenario, work, now)
        rows.append({
            "case_id": scenario.case_id, "family": scenario.family,
            "mode": scenario.mode, "t_days": scenario.t_days, "dims": dims,
        })
        if i % 20 == 0 or i == len(scenarios):
            print(f"[{i}/{len(scenarios)}] done", flush=True)

    aggregate = _aggregate(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps({
            "dataset": "staleness_pressure_v1",
            "per_family": args.per_family,
            "scenarios_sha256": manifest,
            "aggregate": aggregate,
            "rows": rows,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"[manifest] {manifest[:16]}…")
    for name in sorted(aggregate):
        if name.count("/") == 1:  # 只打印 family/mode 级汇总
            print(f"[{name}] {json.dumps(aggregate[name], ensure_ascii=False)}")
    print(f"[results] {out_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
