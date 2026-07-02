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
