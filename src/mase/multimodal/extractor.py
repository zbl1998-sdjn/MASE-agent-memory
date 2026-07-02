"""MediaExtractor 契约:多模态抽取的可插拔接缝。

每个模态(S0 视觉 / S1 语音 / S3 视频)实现同一协议:输入资产信息 +
页图,输出人和测试可直接检视的 ExtractionResult(全文 + 候选事实 +
抽取器/模型/版本)。注册表语义与 agent_registry 一致:同名重注册静默
替换,便于 dev reload;线程安全。
"""
from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .document_loader import MediaPayload


@dataclass(frozen=True)
class MediaAssetInfo:
    """抽取器可见的资产元数据(不含原始字节,字节走 pages)。"""

    media_id: int
    sha256: str
    media_type: str
    source_uri: str | None
    page_count: int


@dataclass(frozen=True)
class CandidateFact:
    """单条候选事实;confidence 为尽力值(模型自报/启发式),非标定概率。"""

    category: str
    key: str
    value: str
    confidence: float
    evidence: str


@dataclass(frozen=True)
class ExtractionResult:
    """一次抽取的完整可审计产物。"""

    full_text: str
    candidate_facts: tuple[CandidateFact, ...]
    extractor_name: str
    model_name: str
    extractor_version: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] | None = None  # 抽取阶段元数据(如 ASR info),随 result_json 入库

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class MediaExtractor(Protocol):
    """模态无关抽取器协议。"""

    name: str
    version: str

    def supports(self, media_type: str) -> bool: ...

    def extract(self, asset: MediaAssetInfo, payload: MediaPayload) -> ExtractionResult: ...


_LOCK = threading.RLock()
_FACTORIES: dict[str, Callable[[], MediaExtractor]] = {}


def register_extractor(name: str, factory: Callable[[], MediaExtractor]) -> None:
    """注册抽取器工厂;同名替换。"""
    if not name or not isinstance(name, str):
        raise ValueError(f"extractor name must be a non-empty string, got {name!r}")
    with _LOCK:
        _FACTORIES[name] = factory


def get_extractor_factory(name: str) -> Callable[[], MediaExtractor] | None:
    with _LOCK:
        return _FACTORIES.get(name)


def extractor_names() -> list[str]:
    with _LOCK:
        return sorted(_FACTORIES)


# ---------- 共享 LLM 回复解析助手(vision / audio 抽取器复用) ----------

_JSON_BLOB_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_blob(raw: str) -> dict[str, Any] | None:
    """从模型回复中提取首个 JSON 对象;失败返回 None(调用方决定降级)。"""
    match = _JSON_BLOB_RE.search(raw)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def coerce_confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
