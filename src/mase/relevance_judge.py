"""LLM 相关性判定(推理型,批量并行 + 判定缓存;显式 API,不自动挂召回)。

NoLiMa 反字面档 POC 取证(2026-07-11,DECISIONS):embedding 相似度不承载
世界知识桥接(三连负结果),而 qwen3:14b + thinking 的逐 chunk yes/no 判定
探针满分(PAIR 6/6),两级管道把该档从 0/68 提到 18/68。本模块把 POC 的
判定层产品化:

- 批量接口 ``judge_relevance_batch(query, texts)``:ThreadPoolExecutor 并行
  (服务端吞吐取决于 ollama ``OLLAMA_NUM_PARALLEL``,客户端并发只是必要
  条件——并行收益必须实测,不得凭默认值声称);
- 判定缓存 ``relevance_judgments`` 表(additive):temp-0 判定确定性可复用,
  同 (query, content, model) 免重判;
- 显式 API:不自动接入任何召回路径(接入是独立决策,POC 已量化每例
  ~2.2 分钟的成本结构,产品化收益待实测)。

延时如实口径:单判定 ~3.8s(qwen3:14b thinking,900 字符 chunk 实测);
并行/缓存后的实际吞吐以真机测量为准。
"""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import httpx

from mase_tools.memory.db_core import get_connection

from .contracts.fact_contract import utc_now

DEFAULT_JUDGE_MODEL = "qwen3:14b"
DEFAULT_WORKERS = 4
_JUDGE_TIMEOUT_S = 300.0

JUDGE_SYSTEM = """You judge whether a text snippet contains information needed to answer a question.
Use world knowledge to bridge (e.g. a landmark implies its city and country).
End your reply with exactly 'ANSWER: yes' or 'ANSWER: no'."""


def judge_model_name() -> str:
    return os.environ.get("MASE_RELEVANCE_JUDGE_MODEL", "").strip() or DEFAULT_JUDGE_MODEL


def judge_workers() -> int:
    raw = os.environ.get("MASE_RELEVANCE_JUDGE_WORKERS", "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_WORKERS
    except ValueError:
        return DEFAULT_WORKERS


def _base_url() -> str:
    raw = str(os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
    if not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"
    return raw.rstrip("/")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def judge_one(query: str, text: str, *, model: str | None = None) -> bool:
    """单次判定(无缓存);失败原样抛,调用方决定降级。"""
    model = model or judge_model_name()
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Question: {query}\nSnippet: {text}\n"
                    "Does the snippet contain information needed to answer the question?"
                ),
            },
        ],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 800},
    }
    if model.startswith("qwen3"):
        # 探针实证:无思考 PAIR 2/6,thinking 6/6——世界知识桥接需要推理 token。
        body["think"] = True
    response = httpx.post(
        f"{_base_url()}/api/chat", json=body,
        timeout=httpx.Timeout(_JUDGE_TIMEOUT_S, connect=10.0),
    )
    response.raise_for_status()
    reply = str((response.json().get("message") or {}).get("content") or "").strip().lower()
    return "answer: yes" in reply


def judge_relevance_batch(
    query: str,
    texts: list[str],
    *,
    model: str | None = None,
    max_workers: int | None = None,
    db_path: str | Path | None = None,
) -> list[bool]:
    """批量判定:缓存命中免重判,未命中并行调用;返回与 texts 对齐的布尔列表。"""
    if not texts:
        return []
    model = model or judge_model_name()
    query_hash = _hash(query or "")
    content_hashes = [_hash(t or "") for t in texts]

    verdicts: dict[int, bool] = {}
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        for index, chash in enumerate(content_hashes):
            row = cursor.execute(
                "SELECT verdict FROM relevance_judgments "
                "WHERE query_hash = ? AND content_hash = ? AND model = ?",
                (query_hash, chash, model),
            ).fetchone()
            if row is not None:
                verdicts[index] = bool(row["verdict"])

    pending = [i for i in range(len(texts)) if i not in verdicts]
    if pending:
        workers = max(1, min(max_workers or judge_workers(), len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fresh = list(pool.map(lambda i: (i, judge_one(query, texts[i], model=model)), pending))
        now = utc_now()
        with closing(get_connection(db_path)) as conn, conn:
            cursor = conn.cursor()
            for index, verdict in fresh:
                verdicts[index] = verdict
                cursor.execute(
                    """
                    INSERT INTO relevance_judgments (query_hash, content_hash, model, verdict, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(query_hash, content_hash, model) DO UPDATE SET
                        verdict = excluded.verdict,
                        created_at = excluded.created_at
                    """,
                    (query_hash, content_hashes[index], model, int(verdict), now),
                )

    return [verdicts[i] for i in range(len(texts))]


__all__ = [
    "DEFAULT_JUDGE_MODEL",
    "JUDGE_SYSTEM",
    "judge_model_name",
    "judge_one",
    "judge_relevance_batch",
    "judge_workers",
]
