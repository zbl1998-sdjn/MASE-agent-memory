"""MediaPayload 接缝形状:图像/PDF 走 pages,音频走 AudioTrack 不预解码。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_load_media_image_fills_pages(tmp_path):
    from mase.multimodal.document_loader import load_media

    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNGdata")
    payload = load_media(img, "image/png")
    assert len(payload.pages) == 1
    assert payload.pages[0].image_bytes == b"\x89PNGdata"
    assert payload.audio is None


def test_load_media_audio_fills_audiotrack_without_decoding(tmp_path):
    from mase.multimodal.document_loader import load_media

    wav = tmp_path / "meeting.wav"
    wav.write_bytes(b"RIFFfake")  # 不解码:损坏字节也能封装
    payload = load_media(wav, "audio/wav")
    assert payload.pages == ()
    assert payload.audio is not None
    assert payload.audio.path == wav
    assert payload.audio.media_type == "audio/wav"
    assert payload.audio.duration_seconds is None


def test_extraction_result_metadata_serializes():
    import json

    from mase.multimodal.extractor import ExtractionResult

    result = ExtractionResult(
        full_text="t", candidate_facts=(), extractor_name="x",
        model_name="m", extractor_version="1", warnings=(),
        metadata={"asr": {"language": "zh"}},
    )
    assert json.loads(result.to_json())["metadata"]["asr"]["language"] == "zh"
