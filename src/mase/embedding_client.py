"""共享的本机 embedding 客户端原语。

从 ``governance/semantic_discovery.py`` 抽出的纯函数:Ollama ``/api/embed``
调用、模型名解析、余弦相似度。两条独立的语义发现路径共用同一份 HTTP/超时/
相似度实现,但各自保留自己的缓存表与召回策略:

- ``governance/semantic_discovery.py``:治理层结构化 facts 的同义改写补漏。
- ``event_semantic_recall.py``:event-log(memory_log)非字面关联召回,
  服务 NoLiMa 反字面档一类"问题与证据零字面重合"的场景。

本模块不做 I/O 之外的业务假设,不感知 facts/event-log 的表结构。
"""
from __future__ import annotations

import math
import os

import httpx

DEFAULT_EMBED_MODEL = "bge-m3"
_EMBED_TIMEOUT_S = 120.0


def embed_model_name() -> str:
    return os.environ.get("MASE_EMBED_MODEL", "").strip() or DEFAULT_EMBED_MODEL


def _embed_base_url() -> str:
    raw = str(os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
    if not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"
    return raw.rstrip("/")


def embed_texts(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """批量取向量;失败原样抛(调用方决定降级),HTTP 带读超时防挂死。"""
    if not texts:
        return []
    response = httpx.post(
        f"{_embed_base_url()}/api/embed",
        json={"model": model or embed_model_name(), "input": texts},
        timeout=httpx.Timeout(_EMBED_TIMEOUT_S, connect=10.0),
    )
    response.raise_for_status()
    embeddings = response.json().get("embeddings") or []
    return [[float(x) for x in vector] for vector in embeddings]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))  # 维度不齐按短边截断
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm > 1e-12 else 0.0


__all__ = [
    "DEFAULT_EMBED_MODEL",
    "cosine_similarity",
    "embed_model_name",
    "embed_texts",
]
