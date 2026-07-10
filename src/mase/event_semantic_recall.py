"""事件路径白盒语义候选发现(诊断 lane;opt-in,默认关)。

治理层 ``governance/semantic_discovery.py`` 服务结构化 facts 的同义改写补漏;
这个模块服务另一条路——``memory_log`` 事件行的**非字面关联**召回,目标场景
是 NoLiMa 反字面档(onehop/twohop/hard):needle 与问题刻意不共享字面词,
纯词法系统(``benchmark_notetaker.search()`` 的 FTS5 BM25 + Python 词项重合;
``HybridReranker`` 的 "dense" 分量也只是复用同一份词法分,全链路无 embedding)
在这一档 committed 0%。

原则与治理层一致:embedding 只做**候选发现,补关键词漏掉的行**,不重排、不
替换关键词已命中的结果——调用方把语义候选作为词法结果之外的**额外**槽位
追加,不占用、不打乱词法排名。这样默认路径(乃至开关打开后词法结果本身)
逐字节不变,新增的只是"词法排不到的东西现在有机会被追加进候选列表"。

**诊断 lane,非 headline 数字**:阈值(0.55)沿用治理层 facts 诊断面(24 事实/
16 改写/8 负例)校准值作为起点,尚未在 NoLiMa/LME 数据上单独校准——按
mase-hardening-backlog 记录("语义发现是该档位的候选杠杆,NoLiMa 侧零证据,
做了必须单列 lane")与 docs/BENCHMARK_ANTI_OVERFIT.md 的 Diagnostics 政策,
在拿到真实 A/B 证据前,这条开关只能用于诊断/研发,不得写进可发布头条分数。

与 ``MASE_SEMANTIC_DISCOVERY``(治理层 facts 开关)是**独立开关**,互不影响、
互不复用彼此的缓存表(facts 与 memory_log 是两张不同 schema 的表)。
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from typing import Any

from mase_tools.memory.db_core import get_connection

from .contracts.fact_contract import utc_now
from .embedding_client import cosine_similarity, embed_model_name, embed_texts

# 沿用治理层 facts 诊断面校准值作为起点(见模块 docstring);NoLiMa/LME 侧
# 待独立诊断集校准,常数可能会变。
DEFAULT_TOP_N = 3
DEFAULT_THRESHOLD = 0.55


def event_semantic_enabled() -> bool:
    """opt-in 开关;默认关,默认召回路径逐字节不变。"""
    return os.environ.get("MASE_EVENT_SEMANTIC_RECALL", "").strip() == "1"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def event_semantic_threshold() -> float:
    return _env_float("MASE_EVENT_SEMANTIC_THRESHOLD", DEFAULT_THRESHOLD)


def event_semantic_top_n() -> int:
    return max(1, int(_env_float("MASE_EVENT_SEMANTIC_TOP_N", float(DEFAULT_TOP_N))))


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _ensure_row_vectors(
    cursor: Any, rows: list[dict[str, Any]], *, model: str
) -> dict[int, list[float]]:
    """按 content_hash 惰性补算/刷新缓存;返回 log_id → 向量。"""
    contents = {int(row["id"]): str(row.get("content") or "") for row in rows}
    hashes = {log_id: _content_hash(text) for log_id, text in contents.items()}
    cached: dict[int, list[float]] = {}
    stale_or_missing: list[int] = []
    for log_id in contents:
        row = cursor.execute(
            "SELECT content_hash, vector_json FROM memory_log_embeddings WHERE log_id = ? AND model = ?",
            (str(log_id), model),
        ).fetchone()
        if row is not None and str(row["content_hash"]) == hashes[log_id]:
            cached[log_id] = [float(x) for x in json.loads(row["vector_json"])]
        else:
            stale_or_missing.append(log_id)
    if stale_or_missing:
        vectors = embed_texts([contents[log_id] for log_id in stale_or_missing], model=model)
        now = utc_now()
        for log_id, vector in zip(stale_or_missing, vectors, strict=True):
            cursor.execute(
                """
                INSERT INTO memory_log_embeddings (log_id, model, content_hash, vector_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(log_id, model) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    vector_json = excluded.vector_json,
                    created_at = excluded.created_at
                """,
                (str(log_id), model, hashes[log_id], json.dumps(vector), now),
            )
            cached[log_id] = vector
    return cached


def discover_events(
    query: str,
    *,
    exclude_ids: set[int] | None = None,
    top_n: int | None = None,
    threshold: float | None = None,
    thread_id: str | None = None,
    db_path: Any = None,
) -> list[tuple[int, float]]:
    """语义发现:返回 [(log_id, similarity)],降序,≥threshold,至多 top_n。

    候选池排除已被关键词命中的行(发现只补漏,不重复计分)与已 superseded
    的行(旧值/已撤回内容不应被发现重新带回)。
    """
    query = (query or "").strip()
    if not query:
        return []
    if top_n is None:
        top_n = event_semantic_top_n()
    if threshold is None:
        threshold = event_semantic_threshold()
    model = embed_model_name()
    exclude = exclude_ids or set()
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        sql = "SELECT id, content FROM memory_log WHERE superseded_at IS NULL"
        params: list[Any] = []
        if thread_id is not None:
            sql += " AND thread_id = ?"
            params.append(thread_id)
        rows = [
            dict(r)
            for r in cursor.execute(sql, params).fetchall()
            if int(r["id"]) not in exclude and str(r["content"] or "").strip()
        ]
        if not rows:
            return []
        vectors = _ensure_row_vectors(cursor, rows, model=model)
    query_vector = embed_texts([query], model=model)[0]
    scored = [
        (log_id, round(cosine_similarity(query_vector, vector), 4))
        for log_id, vector in vectors.items()
    ]
    scored = [(log_id, sim) for log_id, sim in scored if sim >= threshold]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:top_n]


__all__ = [
    "DEFAULT_THRESHOLD",
    "DEFAULT_TOP_N",
    "discover_events",
    "event_semantic_enabled",
    "event_semantic_threshold",
    "event_semantic_top_n",
]
