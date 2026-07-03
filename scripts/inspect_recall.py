"""Recall inspector CLI:一次白盒召回的完整可视化(plan → candidates → pack)。

用法:
    python -X utf8 scripts/inspect_recall.py --keywords 预算,PO-2026 \
        [--question "现在预算是多少?"] [--entity user:default] [--top-k 8] [--db PATH]

PLAN 与 CANDIDATES 两段直接从 retrieval_runs 审计行回放(证明可回放性),
PACK 段为 §4.6.2 模板 markdown。--db 指定库文件(默认走 MASE_DB_PATH 解析)。
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
# 强制置顶(remove+insert):site-packages 存在第三方同名包 `scripts`,
# 若仓根经 .pth 只挂在 sys.path 尾部,`import scripts.*` 会被其抢先命中。
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

from mase.governance.evidence_pack import compile_evidence_pack, render_markdown  # noqa: E402
from mase_tools.memory.db_core import get_connection  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="白盒召回检查器(plan/candidates/pack)")
    parser.add_argument("--keywords", required=True, help="逗号分隔关键词")
    parser.add_argument("--question", default=None, help="用户问题(缺省由关键词生成)")
    parser.add_argument("--entity", default=None, help="按 entity_id 过滤")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--db", type=Path, default=None, help="库文件路径(默认 MASE_DB_PATH)")
    args = parser.parse_args(argv)

    keywords = [kw.strip() for kw in args.keywords.split(",") if kw.strip()]
    question = args.question or f"关于 {'、'.join(keywords)} 的已知事实?"

    pack = compile_evidence_pack(
        question, keywords, entity_id=args.entity, top_k=args.top_k, db_path=args.db
    )

    # 从审计行回放 plan/candidates(而非内存态)——审计表就是回放真源。
    with closing(get_connection(args.db)) as conn:
        run = conn.execute(
            "SELECT plan_json, candidates_json FROM retrieval_runs WHERE trace_id = ?",
            (pack.trace_id,),
        ).fetchone()

    print("=== PLAN ===")
    print(json.dumps(json.loads(run["plan_json"]), ensure_ascii=False, indent=2))
    print()
    print("=== CANDIDATES ===")
    candidates = json.loads(run["candidates_json"])
    if not candidates:
        print("(无候选)")
    for candidate in candidates:
        print(f"- {candidate['fact_id']} [{candidate['status']}] score={candidate['score']}")
        print(f"  claim: {candidate['claim']}")
        print(f"  score_breakdown: {json.dumps(candidate['score_breakdown'], ensure_ascii=False)}")
        for why in candidate["why_selected"]:
            print(f"  why: {why}")
    print()
    print("=== PACK ===")
    print(render_markdown(pack))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
