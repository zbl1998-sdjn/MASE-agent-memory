"""上传路由:真管线+假抽取器;鉴权/只读/类型/大小/去重分支。"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient

from mase.multimodal.extractor import CandidateFact, ExtractionResult


from mase.multimodal.vision_extractor import VISION_EXTRACTOR_VERSION


class _FakeVision:
    # version 必须与生产 VisionExtractor 一致:上传路由按 (name, version) 反查抽取记录,
    # 版本升级时这里跟着产线常量走,防止路由/抽取器版本漂移(P2 实测踩过)。
    name, version = "vision", VISION_EXTRACTOR_VERSION

    def supports(self, media_type):
        return media_type.startswith("image/") or media_type == "application/pdf"

    def extract(self, asset, payload):
        return ExtractionResult(
            full_text="INVOICE ACME-INV-2026-001 total 4200 EUR",
            candidate_facts=(
                CandidateFact("finance_budget", "invoice_total", "4200 EUR", 0.9, "total 4200 EUR"),
            ),
            extractor_name="vision", model_name="fake-vlm",
            extractor_version=VISION_EXTRACTOR_VERSION, warnings=(),
        )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.delenv("MASE_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("MASE_READ_ONLY", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "media_routes.db"))
    monkeypatch.setenv("MASE_MEDIA_ASSETS_DIR", str(tmp_path / "assets"))
    from mase.multimodal import ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "_default_extractors", lambda mode, whisper_model: [_FakeVision()])
    from integrations.openai_compat.server import app

    return TestClient(app)


def test_upload_ingests_and_returns_extraction(client, tmp_path):
    data = b"\x89PNG-s2-invoice"
    resp = client.post(
        "/v1/mase/media/upload",
        files={"file": ("invoice.png", data, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["media_type"] == "image/png"
    assert body["deduplicated"] is False
    assert body["extraction"]["facts"][0]["key"] == "invoice_total"
    assert "ACME-INV-2026-001" in body["extraction"]["full_text_excerpt"]
    assert isinstance(body["media_id"], int)


def test_duplicate_upload_is_deduplicated(client):
    data = b"same-image-bytes"
    files = {"file": ("a.png", data, "image/png")}
    first = client.post("/v1/mase/media/upload", files=files)
    second = client.post("/v1/mase/media/upload", files=files)
    assert first.json()["deduplicated"] is False
    assert second.json()["deduplicated"] is True
    assert second.json()["media_id"] == first.json()["media_id"]


def test_bad_extension_rejected_415(client):
    resp = client.post("/v1/mase/media/upload", files={"file": ("evil.exe", b"MZ", "application/octet-stream")})
    assert resp.status_code == 415


def test_audio_upload_rejected_415(client):
    """S2 上传只收图像/PDF;音频批处理走 CLI(spec §5)。"""
    resp = client.post("/v1/mase/media/upload", files={"file": ("m.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 415


def test_oversize_rejected_413(client, monkeypatch):
    from integrations.openai_compat import media_routes

    monkeypatch.setattr(media_routes, "default_max_bytes", lambda media_type: 16)
    resp = client.post("/v1/mase/media/upload", files={"file": ("big.png", b"x" * 64, "image/png")})
    assert resp.status_code == 413


def test_requires_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("MASE_INTERNAL_API_KEY", "test-internal-key")  # allowlist-secret
    resp = client.post("/v1/mase/media/upload", files={"file": ("a.png", b"x", "image/png")})
    assert resp.status_code in (401, 403)  # 以 auth_dependencies 实际语义为准,两者均为拒绝


def test_read_only_mode_rejects_403(client, monkeypatch):
    monkeypatch.setenv("MASE_READ_ONLY", "1")
    resp = client.post("/v1/mase/media/upload", files={"file": ("a.png", b"x", "image/png")})
    assert resp.status_code == 403
