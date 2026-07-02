"""批处理摄取编排:文件夹 → 逐文件隔离管线 → 带溯源写入白盒记忆。

单文件失败(安全拒绝/损坏/模型故障)只影响该文件:安全与类型问题落
skipped,运行时异常落 infra_errors,批次继续(对齐 benchmarks/runner.py
的 attempt_rows/infra_error 模式)。幂等键 (sha256, extractor, version)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mase_tools.media.asset_store import store_bytes
from mase_tools.memory import tri_vault
from mase_tools.memory.api import (
    mase2_record_extraction,
    mase2_register_media_asset,
    mase2_upsert_fact,
    mase2_write_interaction,
)
from mase_tools.memory.media_records import find_extraction

from .document_loader import load_pages
from .extractor import MediaAssetInfo, MediaExtractor
from .security import (
    DEFAULT_MAX_BYTES,
    IngestSecurityError,
    UnsupportedMedia,
    assert_within_jail,
    classify_media,
)

_SUFFIX_BY_MEDIA_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "application/pdf": "pdf",
}


@dataclass(frozen=True)
class IngestReport:
    """一次批处理的可审计汇总。"""

    processed: tuple[str, ...]
    skipped: tuple[dict[str, Any], ...]
    infra_errors: tuple[dict[str, Any], ...]
    extractions: int
    facts_written: int


def ingest_folder(
    folder: Path,
    *,
    allowed_root: Path | None = None,
    mode: str | None = None,
    extractor: MediaExtractor | None = None,
    force: bool = False,
    asset_root: Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> IngestReport:
    """摄取 folder 下全部受支持文件(递归、字典序,保证批次确定性)。"""
    folder = Path(folder).resolve()
    root = Path(allowed_root).resolve() if allowed_root is not None else folder
    if extractor is None:
        from .vision_extractor import VisionExtractor

        extractor = VisionExtractor(mode=mode)

    processed: list[str] = []
    skipped: list[dict[str, Any]] = []
    infra_errors: list[dict[str, Any]] = []
    extractions = 0
    facts_written = 0

    for file_path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel_name = file_path.relative_to(folder).as_posix()
        try:
            checked = assert_within_jail(file_path, root)
            media_type = classify_media(checked, max_bytes=max_bytes)
        except UnsupportedMedia as exc:
            skipped.append({"file": rel_name, "reason": "unsupported_media", "detail": str(exc)})
            continue
        except IngestSecurityError as exc:
            skipped.append({"file": rel_name, "reason": "security_rejected", "detail": str(exc)})
            continue

        try:
            data = checked.read_bytes()
            sha256, _stored = store_bytes(
                data, suffix=_SUFFIX_BY_MEDIA_TYPE[media_type], root=asset_root
            )
            pages = load_pages(checked, media_type)
            media_id = mase2_register_media_asset(
                sha256,
                source_uri=rel_name,
                media_type=media_type,
                byte_size=len(data),
                page_count=len(pages),
            )
            if not force and find_extraction(
                media_id, extractor_name=extractor.name, extractor_version=extractor.version
            ):
                skipped.append({"file": rel_name, "reason": "already_extracted", "sha256": sha256})
                continue

            asset_info = MediaAssetInfo(
                media_id=media_id, sha256=sha256, media_type=media_type,
                source_uri=rel_name, page_count=len(pages),
            )
            result = extractor.extract(asset_info, pages)
            mase2_record_extraction(
                media_id,
                extractor_name=result.extractor_name,
                model_name=result.model_name,
                extractor_version=result.extractor_version,
                full_text=result.full_text,
                result_json=result.to_json(),
            )
            extractions += 1
            mase2_write_interaction(
                f"ingest::{sha256[:12]}", "system", result.full_text, source_media_id=media_id
            )
            for fact in result.candidate_facts:
                mase2_upsert_fact(
                    fact.category, fact.key, fact.value,
                    reason=f"media_extraction:{sha256}", source_media_id=media_id,
                )
                facts_written += 1
                _mirror_fact_write(fact, sha256=sha256, media_id=media_id)
            processed.append(rel_name)
        except Exception as exc:
            infra_errors.append({"file": rel_name, "error": f"{type(exc).__name__}: {exc}"})

    return IngestReport(
        processed=tuple(processed),
        skipped=tuple(skipped),
        infra_errors=tuple(infra_errors),
        extractions=extractions,
        facts_written=facts_written,
    )


def _mirror_fact_write(fact: Any, *, sha256: str, media_id: int) -> None:
    """tri-vault 磁盘镜像(与 notetaker 同模式):best-effort,失败不破坏主链路。"""
    if not tri_vault.is_enabled():
        return
    try:
        tri_vault.mirror_write(
            "context",
            f"{fact.category}__{fact.key}",
            {
                "tool": "multimodal_ingest",
                "arguments": {"category": fact.category, "key": fact.key, "value": fact.value,
                              "source_media_id": media_id, "sha256": sha256},
                "result": f"media_extraction:{sha256}",
                "ts": int(time.time() * 1000),
            },
        )
    except Exception:
        pass
