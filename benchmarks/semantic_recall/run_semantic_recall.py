"""治理层语义发现的同义改写召回评测(诊断面,真实 embedding,A/B 口径)。

固定 24 条已治理事实(16 条被查询 + 8 条纯噪声池),16 条零关键词重叠的
中文同义改写查询 + 8 条完全无关的负例查询;同一库上分别以
MASE_SEMANTIC_DISCOVERY=0/1 走 compile_evidence_pack,机械判分:

- paraphrase_hit_rate:目标事实进入 Verified(改写查询)
- extra_noise_rate:改写查询里混入非目标事实
- negative_false_rate:负例查询任何事实被 Verified
- mean_latency_s:on 模式热缓存单查询耗时

定位:**诊断面**(调 threshold/weight 用),非冻结 holdout;对抗性 lane
禁用该 flag 的政策见 docs/BENCHMARK_ANTI_OVERFIT.md。

用法:
    python -X utf8 benchmarks/semantic_recall/run_semantic_recall.py [--out-root DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for _p in (_REPO / "src", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# (predicate, value);前 16 条有配对查询,后 8 条为噪声池(不被查询)。
FACTS: list[tuple[str, str]] = [
    ("reimburse_cap", "每月报销上限 500 元"),
    ("editor_pref", "日常主用 Neovim 编辑器"),
    ("meeting_room", "例会固定在北楼三层小会议室"),
    ("coffee_order", "美式咖啡不加糖"),
    ("deploy_window", "生产发布窗口是周四晚十点后"),
    ("db_engine", "主库用 PostgreSQL 15"),
    ("vpn_access", "远程接入走公司自建 WireGuard"),
    ("backup_policy", "备份每天凌晨三点全量一次"),
    ("expense_tool", "报销流程走钉钉审批"),
    ("laptop_model", "工作机是 ThinkPad X1 Carbon"),
    ("team_size", "算法组现在有七个人"),
    ("holiday_plan", "十月打算去云南休假"),
    ("food_allergy", "对花生严重过敏"),
    ("gym_schedule", "每周二和周四晚上去健身房"),
    ("kid_school", "女儿在实验二小读三年级"),
    ("parking_spot", "车位在地下二层 B217"),
    # 噪声池(永不查询,考察误发现)
    ("printer_loc", "彩色打印机在茶水间旁边"),
    ("wifi_guest", "访客网络叫 Guest-5F"),
    ("stand_desk", "工位是电动升降桌"),
    ("plant_care", "绿萝每周五浇一次水"),
    ("badge_policy", "门禁卡丢失当天必须挂失"),
    ("snack_shelf", "零食架每周一补货"),
    ("shuttle_bus", "班车晚上七点从东门发车"),
    ("mouse_model", "鼠标是罗技 MX Master 3"),
]

# (查询, 目标 predicate);查询与目标事实零关键词重叠(整短语不为任何字段子串)。
PARAPHRASE_QUERIES: list[tuple[str, str]] = [
    ("每个月最多能报销多少钱", "reimburse_cap"),
    ("平时写代码惯用什么工具", "editor_pref"),
    ("周会一般安排在哪个房间", "meeting_room"),
    ("他喝咖啡有什么讲究", "coffee_order"),
    ("新版本什么时候可以上线", "deploy_window"),
    ("后端选型用的哪个数据库", "db_engine"),
    ("在家办公怎么连内网", "vpn_access"),
    ("数据多久做一次完整备份", "backup_policy"),
    ("费用单据在哪个系统提交", "expense_tool"),
    ("他用的笔记本是什么型号", "laptop_model"),
    ("那个小组现在规模多大", "team_size"),
    ("假期他准备去哪里玩", "holiday_plan"),
    ("聚餐点菜需要避开什么食材", "food_allergy"),
    ("他通常什么时候锻炼身体", "gym_schedule"),
    ("孩子目前在哪里念书", "kid_school"),
    ("他的车一般停在什么位置", "parking_spot"),
]

NEGATIVE_QUERIES: list[str] = [
    "公司股票代码是多少",
    "食堂今天中午有什么菜",
    "年终奖大概什么时候发",
    "机房现在温度是多少度",
    "新来的同事叫什么名字",
    "世界杯冠军是哪支球队",
    "明天会不会下雨",
    "最近的地铁站怎么走",
]


def _seed(db_path: Path) -> dict[str, str]:
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    predicate_to_fact_id: dict[str, str] = {}
    for i, (predicate, value) in enumerate(FACTS):
        final = propose_fact(
            FactContract(
                fact_id=new_fact_id(),
                entity_id="user:semrecall",
                claim_type="preference",
                subject="sem_user",
                predicate=predicate,
                object_value=value,
                confidence=0.9,
                observed_at=f"2026-06-{(i % 28) + 1:02d}T00:00:00Z",
            ),
            value,
            source_type="chat",
            source_id=f"seed-{i}",
            trust_level=3,
            source_full_text=f"用户提到:{value}。",
            db_path=db_path,
        )
        if final.status != "active":
            raise RuntimeError(f"seed not active: {predicate} -> {final.status}")
        predicate_to_fact_id[predicate] = final.fact_id
    return predicate_to_fact_id


def _run_mode(
    mode: str, db_path: Path, fact_ids: dict[str, str]
) -> dict[str, Any]:
    from mase.governance.evidence_pack import compile_evidence_pack

    os.environ["MASE_SEMANTIC_DISCOVERY"] = "1" if mode == "on" else "0"
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    hit = extra_noise = 0
    for query, target in PARAPHRASE_QUERIES:
        started = time.perf_counter()
        pack = compile_evidence_pack(query, [query], db_path=db_path)
        latencies.append(time.perf_counter() - started)
        verified_ids = {str(v["fact_id"]) for v in pack.verified}
        got = fact_ids[target] in verified_ids
        noise = bool(verified_ids - {fact_ids[target]})
        hit += got
        extra_noise += noise
        rows.append({"query": query, "kind": "paraphrase", "target": target,
                     "hit": got, "noise": noise, "verified_count": len(verified_ids)})
    false_positive = 0
    for query in NEGATIVE_QUERIES:
        started = time.perf_counter()
        pack = compile_evidence_pack(query, [query], db_path=db_path)
        latencies.append(time.perf_counter() - started)
        leaked = len(pack.verified) > 0
        false_positive += leaked
        rows.append({"query": query, "kind": "negative", "false_verified": leaked,
                     "verified_count": len(pack.verified)})
    return {
        "paraphrase_hit_rate": round(hit / len(PARAPHRASE_QUERIES), 4),
        "extra_noise_rate": round(extra_noise / len(PARAPHRASE_QUERIES), 4),
        "negative_false_rate": round(false_positive / len(NEGATIVE_QUERIES), 4),
        "mean_latency_s": round(sum(latencies) / len(latencies), 3),
        "max_latency_s": round(max(latencies), 3),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="semantic paraphrase recall A/B (diagnostic)")
    parser.add_argument("--out-root", default="E:/MASE-runs/eval_runs")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_root).resolve() / f"semantic_recall_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "facts.db"
    fact_ids = _seed(db_path)

    results = {}
    for mode in ("off", "on"):
        results[mode] = _run_mode(mode, db_path, fact_ids)
        summary = {k: v for k, v in results[mode].items() if k != "rows"}
        print(f"[{mode}] {json.dumps(summary, ensure_ascii=False)}", flush=True)
    # on 模式跑第二遍取热缓存延迟(首遍含 24 条事实向量建库)。
    results["on_warm"] = _run_mode("on", db_path, fact_ids)
    warm = {k: v for k, v in results["on_warm"].items() if k != "rows"}
    print(f"[on_warm] {json.dumps(warm, ensure_ascii=False)}")

    (out_dir / "results.json").write_text(
        json.dumps({
            "dataset": "semantic_recall_diagnostic_v1",
            "facts": len(FACTS),
            "paraphrase_queries": len(PARAPHRASE_QUERIES),
            "negative_queries": len(NEGATIVE_QUERIES),
            "embed_model": os.environ.get("MASE_EMBED_MODEL") or "bge-m3",
            "results": results,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"[results] {out_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
