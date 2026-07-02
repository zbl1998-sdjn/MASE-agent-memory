"""摄取安全边界:路径 jail + 类型/大小 allowlist。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_jail_allows_inside_and_rejects_escape(tmp_path):
    from mase.multimodal.security import JailViolation, assert_within_jail

    root = tmp_path / "docs"
    root.mkdir()
    inside = root / "a" / "scan.png"
    inside.parent.mkdir()
    inside.write_bytes(b"x")

    assert assert_within_jail(inside, root) == inside.resolve()

    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    with pytest.raises(JailViolation):
        assert_within_jail(outside, root)
    with pytest.raises(JailViolation):
        assert_within_jail(root / ".." / "secret.png", root)


def test_classify_media_allowlist(tmp_path):
    from mase.multimodal.security import UnsupportedMedia, classify_media

    png = tmp_path / "a.PNG"  # 大小写不敏感
    png.write_bytes(b"x" * 10)
    assert classify_media(png) == "image/png"

    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF")
    assert classify_media(pdf) == "application/pdf"

    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(UnsupportedMedia):
        classify_media(exe)


def test_classify_media_rejects_oversize(tmp_path):
    from mase.multimodal.security import UnsupportedMedia, classify_media

    big = tmp_path / "big.png"
    big.write_bytes(b"x" * 1024)
    with pytest.raises(UnsupportedMedia):
        classify_media(big, max_bytes=512)


def test_audio_types_in_allowlist(tmp_path):
    from mase.multimodal.security import classify_media

    for name, expected in (
        ("m.wav", "audio/wav"),
        ("m.MP3", "audio/mpeg"),
        ("m.m4a", "audio/mp4"),
        ("m.flac", "audio/flac"),
    ):
        f = tmp_path / name
        f.write_bytes(b"x" * 10)
        assert classify_media(f) == expected


def test_per_type_default_max_bytes():
    """None → 音频 500MB / 图像 50MB 分档;显式 max_bytes 仍全类型统一。"""
    from mase.multimodal.security import AUDIO_MAX_BYTES, DEFAULT_MAX_BYTES, default_max_bytes

    assert default_max_bytes("audio/mpeg") == AUDIO_MAX_BYTES == 500 * 1024 * 1024
    assert default_max_bytes("image/png") == DEFAULT_MAX_BYTES


def test_audio_over_image_cap_but_under_audio_cap_passes(tmp_path, monkeypatch):
    from mase.multimodal import security
    from mase.multimodal.security import classify_media

    big_audio = tmp_path / "long.mp3"
    big_audio.write_bytes(b"x" * 128)
    # 通过打小上限常量模拟"超图像档但在音频档内",避免真写 60MB 文件
    monkeypatch.setattr(security, "DEFAULT_MAX_BYTES", 64)
    monkeypatch.setattr(security, "AUDIO_MAX_BYTES", 256)
    assert classify_media(big_audio) == "audio/mpeg"  # None → 按类型默认,128 < 256
