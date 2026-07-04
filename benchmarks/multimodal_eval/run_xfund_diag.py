"""XFUND-train 诊断集跑分器(复用 run_eval 的 run_case/_aggregate)。

诊断集不是冻结正式集:无 manifest 哈希校验,不产出正式成绩;仅供优化期
中文表单取证与模型 A/B 的验证面。案例文件绝对路径,synthetic_root 无关。

用法:
    python -X utf8 benchmarks/multimodal_eval/run_xfund_diag.py [--limit N] [--vision-mode minicpm]
产物落 E:/MASE-runs/eval_runs/xfund_diag_<ts>/{results.json}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for _p in (_REPO / "src", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from run_eval import _aggregate, run_case  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="XFUND-train 诊断集跑分(非正式)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--vision-mode", default=None)
    parser.add_argument("--out-root", default="E:/MASE-runs/eval_runs")
    parser.add_argument("--stamp", default="manual", help="输出目录时间戳(脚本内不取系统时间)")
    args = parser.parse_args()

    diag = json.loads((_HERE / "diag_xfund_train.json").read_text(encoding="utf-8"))
    cases = diag["cases"][: args.limit] if args.limit else diag["cases"]
    out_dir = Path(args.out_root).resolve() / f"xfund_diag_{args.stamp}"
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for i, case in enumerate(cases, 1):
        dims = run_case(case, work, _HERE, args.vision_mode, None)
        rows.append({"case_id": case["case_id"], "lane": case["lane"], "dims": dims})
        print(f"[{i}/{len(cases)}] {case['case_id']} "
              f"facts={dims.get('facts_hit')}/{dims.get('facts_total')} "
              f"infra={dims.get('infra_error')}", flush=True)

    agg = _aggregate(rows)
    (out_dir / "results.json").write_text(
        json.dumps({"dataset": "xfund_diag_train", "split": "diagnostic",
                    "vision_mode": args.vision_mode, "aggregate": agg, "rows": rows},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"[overall] {json.dumps(agg, ensure_ascii=False)}")
    print(f"[results] {out_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
