"""内容寻址媒体资产库:哈希稳定、去重、写路径 jail。"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_store_bytes_is_content_addressed_and_dedups(tmp_path):
    from mase_tools.media.asset_store import asset_path, store_bytes

    data = b"fake png bytes"
    sha, path1 = store_bytes(data, suffix="png", root=tmp_path)
    assert sha == hashlib.sha256(data).hexdigest()
    assert path1 == tmp_path / sha[:2] / f"{sha}.png"
    assert path1.read_bytes() == data

    mtime = path1.stat().st_mtime_ns
    sha2, path2 = store_bytes(data, suffix="png", root=tmp_path)
    assert (sha2, path2) == (sha, path1)
    assert path1.stat().st_mtime_ns == mtime  # 已存在不重写

    assert asset_path(sha, root=tmp_path) == path1
    assert asset_path("0" * 64, root=tmp_path) is None


def test_store_bytes_rejects_pathy_suffix(tmp_path):
    """suffix 只允许短字母数字,防止拼路径逃逸。"""
    from mase_tools.media.asset_store import AssetStoreError, store_bytes

    for bad in ("../evil", "a/b", "png\\..", "x" * 20, ""):
        with pytest.raises(AssetStoreError):
            store_bytes(b"data", suffix=bad, root=tmp_path)


def test_resolve_asset_root_priority(tmp_path, monkeypatch):
    from mase_tools.media.asset_store import resolve_asset_root

    monkeypatch.setenv("MASE_MEDIA_ASSETS_DIR", str(tmp_path / "explicit"))
    monkeypatch.setenv("MASE_RUNS_DIR", str(tmp_path / "runs"))
    assert resolve_asset_root() == (tmp_path / "explicit").resolve()

    monkeypatch.delenv("MASE_MEDIA_ASSETS_DIR")
    assert resolve_asset_root() == (tmp_path / "runs" / "media_assets").resolve()
