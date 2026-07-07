"""事件→事实投影切片①:存量对话事件的确定性批量投影(设计 2026-07-08)。

只投影 ``role='user'`` 且未 superseded 的 memory_log 行:用确定性
``parse_kv_lines``(零 LLM,值逐字来自事件原文)抽出键值,逐条经
``GovernedFactWriteFacade.record_notetaker_fact(source_log_id=…)`` 提交——
候选留痕、trust 推断(逐字=5)、G2/G3/G5 门控、同键 supersede 全部复用,
唯一写入口不变式不破。幂等双保险:候选表按 source_log_id 跳过已投影事件,
propose_fact 既有 (键,值,quote_hash) 去重兜底。
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from mase.multimodal.kv_extract import parse_kv_lines
from mase_tools.memory.db_core import get_connection

from .write_facade import GovernedFactWriteFacade, _ensure_candidate_schema


def _already_projected_log_ids(conn: Any) -> set[int]:
    _ensure_candidate_schema(conn)
    rows = conn.execute(
        "SELECT DISTINCT source_log_id FROM governance_fact_candidates WHERE source_log_id IS NOT NULL"
    ).fetchall()
    return {int(row[0]) for row in rows}


def project_events(
    *,
    thread_id: str | None = None,
    limit: int | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """把存量 user 事件投影为治理 facts;返回逐项计数报告。

    只扫描未投影过的事件(候选表 source_log_id 判定);闲聊(无 ``键:值``
    结构)事件零产出并计入 events_no_facts,不留候选。
    """
    with closing(get_connection(db_path)) as conn:
        done = _already_projected_log_ids(conn)
        sql = (
            "SELECT id, content FROM memory_log "
            "WHERE role = 'user' AND superseded_at IS NULL"
        )
        params: list[Any] = []
        if thread_id is not None:
            sql += " AND thread_id = ?"
            params.append(thread_id)
        sql += " ORDER BY id"
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

    facade = GovernedFactWriteFacade()
    events_scanned = 0
    events_skipped = 0
    events_no_facts = 0
    events_projected = 0
    facts_proposed = 0
    facts_failed = 0
    facts_by_status: dict[str, int] = {}
    for row in rows:
        if limit is not None and events_projected >= limit:
            break
        events_scanned += 1
        log_id = int(row["id"])
        if log_id in done:
            events_skipped += 1
            continue
        content = str(row["content"] or "")
        candidates = parse_kv_lines(content)
        if not candidates:
            events_no_facts += 1
            continue
        events_projected += 1
        for fact in candidates:
            outcome = facade.record_notetaker_fact(
                fact.category,
                fact.key,
                fact.value,
                reason="event_projection.v1",
                source_log_id=log_id,
                evidence_text=fact.evidence,
                evidence_source_type="memory_log",
                evidence_source_id=str(log_id),
                db_path=db_path,
            )
            facts_proposed += 1
            if outcome.governance_error:
                facts_failed += 1
            else:
                status = str(outcome.fact_status or "unknown")
                facts_by_status[status] = facts_by_status.get(status, 0) + 1
    return {
        "events_scanned": events_scanned,
        "events_skipped_already_projected": events_skipped,
        "events_no_facts": events_no_facts,
        "events_projected": events_projected,
        "facts_proposed": facts_proposed,
        "facts_by_status": facts_by_status,
        "facts_failed": facts_failed,
    }


__all__ = ["project_events"]
