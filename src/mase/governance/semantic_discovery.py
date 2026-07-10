"""白盒语义候选发现(企业 Phase 5 起步;opt-in,默认关)。

原则:embedding 只做**候选发现**——补充关键词 substring 漏掉的事实,绝不放宽
Verified 门槛(active + 已定位 span 仍是编译器唯一准入)。相似度、模型名、
阈值全部进 retrieval plan 与候选 breakdown(retrieval_runs 落库可回放);
相似度本身依赖模型,但"以什么依据、什么分值入选"是完整留痕的。

事实向量缓存在 additive 表 fact_embeddings(content_hash 变更即重算);
查询向量每次现算。Ollama /api/embed,默认 bge-m3(中文语料主场),
`MASE_EMBED_MODEL` 可换,HTTP 全程带超时(继承传输层加固纪律)。

历史教训(DECISIONS.md 2026-04-18 双针对抗诊断):在 LV-Eval 式对抗性植入
场景,bge-m3 把正确答案排在最后(distractor 0.64 > decoy 0.62 > true 0.42)
——embedding 偏爱通顺文本,而对抗针故意带错别字,语义信号在该面上是净负项。
因此本开关**默认关**,且对抗性跑分 lane 永远不得开启(反过拟合政策
docs/BENCHMARK_ANTI_OVERFIT.md "Adversarial-Lane Feature Flags" 节)。本模块
的适用面是治理层结构化 facts 的同义改写补漏,与原文窗口检索是两回事。
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import get_connection

from ..embedding_client import cosine_similarity, embed_model_name, embed_texts
from .fact_contract import utc_now

# 2026-07-07 诊断面校准(benchmarks/semantic_recall,24 事实/16 改写/8 负例):
# top_n=1 零代价消噪(目标过阈值时总是语义第一名);threshold 0.55 精确优先
# (负例顶点 0.514,留 0.036 边距;0.5 档命中 0.94 但负例误发现 25%,
# 高召回场景用 MASE_SEMANTIC_THRESHOLD=0.5 自选)。
DEFAULT_TOP_N = 1
DEFAULT_THRESHOLD = 0.55
# 弱语义线索带 [hint_floor, threshold):不作应答材料,进 Evidence Pack 的
# 非应答线索节供上层追问(设计 2026-07-07-mase-semantic-hints-design.md)。
DEFAULT_HINT_FLOOR = 0.50
HINT_CAP = 3
# 语义分量权重:低于任何强关键词命中(exact_entity 0.30/predicate 0.20),
# 发现是补充信号,不与机械匹配争主导。常数待 NoLiMa/LME 侧 A/B 校准。
SEMANTIC_WEIGHT = 0.15


def semantic_enabled() -> bool:
    """opt-in 开关;默认关,默认召回路径逐字节不变。"""
    return os.environ.get("MASE_SEMANTIC_DISCOVERY", "").strip() == "1"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def semantic_threshold() -> float:
    """相似度准入阈值(`MASE_SEMANTIC_THRESHOLD` 可覆盖,校准见诊断面)。"""
    return _env_float("MASE_SEMANTIC_THRESHOLD", DEFAULT_THRESHOLD)


def semantic_top_n() -> int:
    """每查询语义候选上限(`MASE_SEMANTIC_TOP_N` 可覆盖)。"""
    return max(1, int(_env_float("MASE_SEMANTIC_TOP_N", float(DEFAULT_TOP_N))))


def semantic_hint_floor() -> float:
    """弱线索带下界(`MASE_SEMANTIC_HINT_FLOOR`);floor ≥ threshold 即关闭线索带。"""
    return _env_float("MASE_SEMANTIC_HINT_FLOOR", DEFAULT_HINT_FLOOR)


def _fact_content(row: Any) -> str:
    return f"{row['subject']}.{row['predicate']} = {row['object']}"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _ensure_fact_vectors(
    cursor: Any, rows: list[Any], *, model: str
) -> dict[str, list[float]]:
    """按 content_hash 惰性补算/刷新缓存;返回 fact_id → 向量。"""
    contents = {str(row["fact_id"]): _fact_content(row) for row in rows}
    hashes = {fid: _content_hash(text) for fid, text in contents.items()}
    cached: dict[str, list[float]] = {}
    stale_or_missing: list[str] = []
    for fid in contents:
        row = cursor.execute(
            "SELECT content_hash, vector_json FROM fact_embeddings WHERE fact_id = ? AND model = ?",
            (fid, model),
        ).fetchone()
        if row is not None and str(row["content_hash"]) == hashes[fid]:
            cached[fid] = [float(x) for x in json.loads(row["vector_json"])]
        else:
            stale_or_missing.append(fid)
    if stale_or_missing:
        vectors = embed_texts([contents[fid] for fid in stale_or_missing], model=model)
        now = utc_now()
        for fid, vector in zip(stale_or_missing, vectors, strict=True):
            cursor.execute(
                """
                INSERT INTO fact_embeddings (fact_id, model, content_hash, vector_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(fact_id, model) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    vector_json = excluded.vector_json,
                    created_at = excluded.created_at
                """,
                (fid, model, hashes[fid], json.dumps(vector), now),
            )
            cached[fid] = vector
    return cached


def discover(
    keywords: list[str],
    *,
    entity_id: str | None = None,
    exclude_fact_ids: set[str] | None = None,
    top_n: int | None = None,
    threshold: float | None = None,
    db_path: str | Path | None = None,
) -> list[tuple[str, float]]:
    """语义发现:返回 [(fact_id, similarity)],降序,≥threshold,至多 top_n。

    候选池仅 **active + quarantined**(可选 entity 过滤),排除已被关键词命中
    的事实(发现只补漏,不重复计分)。quarantined 保留:它进 pack 的
    do_not_assume 节是防幻觉特性。superseded/retracted/rejected 不进池:
    旧链节点若可被发现只会抢走 top_n 名额并构成答旧值幻觉面(2026-07-08
    POC 取证:top_n=1 名额被 superseded 旧值占据,active 现行值落选 →
    pack 空 → 弃答)。
    """
    query = " ".join(kw for kw in keywords if kw and kw.strip()).strip()
    if not query:
        return []
    if top_n is None:
        top_n = semantic_top_n()
    if threshold is None:
        threshold = semantic_threshold()
    model = embed_model_name()
    exclude = exclude_fact_ids or set()
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        sql = "SELECT fact_id, subject, predicate, object FROM facts WHERE status IN ('active', 'quarantined')"
        params: list[Any] = []
        if entity_id is not None:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        rows = [r for r in cursor.execute(sql, params).fetchall() if str(r["fact_id"]) not in exclude]
        if not rows:
            return []
        vectors = _ensure_fact_vectors(cursor, rows, model=model)
    query_vector = embed_texts([query], model=model)[0]
    scored = [
        (fid, round(cosine_similarity(query_vector, vector), 4))
        for fid, vector in vectors.items()
    ]
    scored = [(fid, sim) for fid, sim in scored if sim >= threshold]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:top_n]


__all__ = [
    "DEFAULT_THRESHOLD",
    "DEFAULT_TOP_N",
    "SEMANTIC_WEIGHT",
    "discover",
    "embed_model_name",
    "embed_texts",
    "semantic_enabled",
]
