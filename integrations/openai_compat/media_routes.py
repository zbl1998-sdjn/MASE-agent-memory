"""交互式媒体上传路由(S2):multipart → S0 摄取管线 → 抽取结果回显。

只收图像/PDF 直传字节;不接受 URL(零 SSRF 面);大小上限先于落盘;
临时目录请求结束即删(资产库已有内容寻址副本)。写记忆 → 只读模式拒绝,
配置 token 后必须带 key。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from integrations.openai_compat.auth_dependencies import (
    require_internal_api_key,
    require_writable_mode,
)
from mase.multimodal.ingest import ingest_folder
from mase.multimodal.security import ALLOWED_MEDIA_TYPES, default_max_bytes
from mase.multimodal.vision_extractor import VISION_EXTRACTOR_VERSION
from mase_tools.memory.media_records import find_extraction, get_media_asset

router = APIRouter()

_EXCERPT_CHARS = 500
_CHUNK = 1 * 1024 * 1024


@router.post("/v1/mase/media/upload")
def upload_media(
    file: UploadFile,
    mode: str | None = Form(default=None),
    _auth: None = Depends(require_internal_api_key),
) -> dict[str, Any]:
    require_writable_mode()

    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    media_type = ALLOWED_MEDIA_TYPES.get(suffix)
    if media_type is None or media_type.startswith("audio/"):
        # S2 交互上传只收图像/PDF;音频批量入库走 CLI(spec §5/§9)。
        raise HTTPException(status_code=415, detail=f"unsupported media type: {suffix!r}")

    max_bytes = default_max_bytes(media_type)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = file.file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"file exceeds {max_bytes} bytes")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    sha256 = hashlib.sha256(data).hexdigest()

    # 幂等预检:资产已存在时,若管线报 already_extracted 则回显既有抽取。
    existing = get_media_asset(sha256=sha256)

    tmp_dir = Path(tempfile.mkdtemp(prefix="mase_upload_"))
    try:
        (tmp_dir / filename).write_bytes(data)
        report = ingest_folder(tmp_dir, mode=mode)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if report.infra_errors:
        raise HTTPException(status_code=502, detail={"infra_errors": list(report.infra_errors)})
    deduplicated = existing is not None and any(
        s.get("reason") == "already_extracted" for s in report.skipped
    )

    asset = get_media_asset(sha256=sha256)
    if asset is None:
        raise HTTPException(status_code=502, detail="asset registration missing after ingest")
    extraction = find_extraction(
        int(asset["id"]), extractor_name="vision", extractor_version=VISION_EXTRACTOR_VERSION
    )
    if extraction is None:
        raise HTTPException(status_code=502, detail="extraction record missing after ingest")

    result_json = json.loads(extraction.get("result_json") or "{}")
    return {
        "media_id": int(asset["id"]),
        "sha256": sha256,
        "media_type": media_type,
        "deduplicated": deduplicated,
        "extraction": {
            "extractor": extraction["extractor_name"],
            "model": extraction["model_name"],
            "version": extraction["extractor_version"],
            "full_text_excerpt": str(extraction.get("full_text") or "")[:_EXCERPT_CHARS],
            "facts": result_json.get("candidate_facts", []),
            "warnings": result_json.get("warnings", []),
        },
    }
