"""Markdown fact sheet 导出:每个 entity 一份人可读事实账本。

分 Active / Superseded / Quarantined 三节(其余状态只计数不列出,页脚如实标注);
每行含 fact_id 短址、claim、证据来源+span、observed_at,内容与 facts 四表一致。

用法:
    python -X utf8 scripts/export_fact_sheets.py [--out DIR] [--entity ID]

默认输出目录:$MASE_RUNS_DIR/fact_sheets/,未设 MASE_RUNS_DIR 时 run_artifacts/fact_sheets/。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.governance.fact_contract import SCHEMA_VERSION, utc_now  # noqa: E402
from mase.governance.fact_store import get_fact, list_facts  # noqa: E402

SECTION_ORDER = ("active", "superseded", "quarantined")


def _default_out_dir() -> Path:
    runs_dir = os.environ.get("MASE_RUNS_DIR")
    if runs_dir:
        return Path(runs_dir).expanduser() / "fact_sheets"
    return _ROOT / "run_artifacts" / "fact_sheets"


def _sanitize_entity(entity_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", entity_id)


def _cell(value: Any) -> str:
    """markdown 表格单元:竖线转义、换行压平。"""
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _evidence_cell(evidence: list[dict[str, Any]]) -> str:
    parts = []
    for span in evidence:
        loc = (
            f"[{span['span_start']}:{span['span_end']}]"
            if span["span_start"] is not None
            else "[未定位]"
        )
        excerpt = str(span.get("quote_excerpt") or "")
        if len(excerpt) > 60:
            excerpt = excerpt[:60] + "…"
        parts.append(f"{span['source_type']}:{span['source_id']} {loc} “{excerpt}”")
    return _cell("; ".join(parts) if parts else "(无)")


def _consolidated_members(entity_id: str, *, db_path: str | Path | None) -> dict[str, str]:
    """member fact_id → active 摘要 fact_id;只认 active 摘要,retract 后自动还原展开。"""
    from contextlib import closing  # noqa: PLC0415

    from mase_tools.memory.db_core import get_connection  # noqa: PLC0415

    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT e.from_fact_id AS summary_id, e.to_fact_id AS member_id
            FROM fact_edges e JOIN facts f ON f.fact_id = e.from_fact_id
            WHERE e.edge_type = 'consolidates' AND f.status = 'active' AND f.entity_id = ?
            """,
            (entity_id,),
        ).fetchall()
    return {str(row["member_id"]): str(row["summary_id"]) for row in rows}


def _render_sheet(entity_id: str, facts: list[dict[str, Any]], *, db_path: str | Path | None) -> str:
    lines = [
        "---",
        f"schema_version: {SCHEMA_VERSION}",
        f"entity_id: {entity_id}",
        f"generated_at: {utc_now()}",
        "---",
        "",
        f"# Fact Sheet — {entity_id}",
        "",
    ]
    by_status: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        by_status.setdefault(str(fact["status"]), []).append(fact)

    folded_by = _consolidated_members(entity_id, db_path=db_path)
    for status in SECTION_ORDER:
        rows = by_status.get(status, [])
        folded: dict[str, int] = {}
        if status == "superseded" and folded_by:
            kept = []
            for fact in rows:
                summary_id = folded_by.get(str(fact["fact_id"]))
                if summary_id is None:
                    kept.append(fact)
                else:
                    folded[summary_id] = folded.get(summary_id, 0) + 1
            rows = kept
        lines.append(f"## {status.capitalize()}")
        lines.append("")
        for summary_id, count in sorted(folded.items()):
            lines.append(
                f"> 已折叠 {count} 行历史版本到摘要 {_cell(summary_id[:17])}"
                "(derived_summary;retract 摘要即还原展开)"
            )
        if folded:
            lines.append("")
        if not rows:
            lines.append("(无)" if not folded else "(其余无)")
            lines.append("")
            continue
        lines.append("| fact_id | claim | evidence | observed_at |")
        lines.append("|---|---|---|---|")
        for fact in rows:
            detail = get_fact(str(fact["fact_id"]), db_path=db_path) or {"evidence": []}
            claim = f"{fact['subject']}.{fact['predicate']} = {fact['object']}"
            lines.append(
                "| {fid} | {claim} | {evidence} | {observed} |".format(
                    fid=_cell(str(fact["fact_id"])[:17]),
                    claim=_cell(claim),
                    evidence=_evidence_cell(detail["evidence"]),
                    observed=_cell(fact["observed_at"]),
                )
            )
        lines.append("")

    hidden = {s: len(r) for s, r in by_status.items() if s not in SECTION_ORDER}
    if hidden:
        summary = ", ".join(f"{s}: {n}" for s, n in sorted(hidden.items()))
        lines.append(f"> 另有未列出状态:{summary}(用 fact_store.list_facts 查询)")
        lines.append("")
    return "\n".join(lines)


def export_fact_sheets(
    *,
    out_dir: Path | None = None,
    entity_id: str | None = None,
    db_path: str | Path | None = None,
) -> list[Path]:
    """导出 fact sheet,返回写出的文件路径(按 entity 排序)。"""
    facts = list_facts(entity_id=entity_id, db_path=db_path)
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        by_entity.setdefault(str(fact["entity_id"]), []).append(fact)
    if not by_entity:
        return []

    target = Path(out_dir) if out_dir is not None else _default_out_dir()
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for eid in sorted(by_entity):
        sheet = _render_sheet(eid, by_entity[eid], db_path=db_path)
        path = target / f"{_sanitize_entity(eid)}.md"
        path.write_text(sheet, encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 governance fact sheet(markdown)")
    parser.add_argument("--out", type=Path, default=None, help="输出目录(默认 MASE_RUNS_DIR/fact_sheets)")
    parser.add_argument("--entity", default=None, help="只导出指定 entity_id")
    args = parser.parse_args(argv)

    written = export_fact_sheets(out_dir=args.out, entity_id=args.entity)
    if not written:
        print("没有可导出的事实(facts 表为空或过滤后为空)。")
        return 0
    for path in written:
        print(f"wrote {path}")
    print(f"共 {len(written)} 份 fact sheet。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
