"""内容寻址媒体资产库。

原始媒体字节按 sha256 存放在 ``<root>/<sha[:2]>/<sha>.<suffix>``,是白盒
溯源链的最底层锚点:media_asset.sha256 → 本库文件 → 原始字节。
写路径固定在 resolve_asset_root() 之下(路径 jail),suffix 白名单校验,
同哈希文件已存在时直接复用,不重复写盘。
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from mase_tools.memory.db_core import _resolve_memory_dir

_SUFFIX_RE = re.compile(r"^[a-z0-9]{1,5}$")


class AssetStoreError(Exception):
    """资产库写入被拒(非法 suffix / 越界路径)。"""


def resolve_asset_root() -> Path:
    """资产根目录:显式 env → MASE_RUNS_DIR 下 → 默认 memory 目录下。"""
    explicit = os.environ.get("MASE_MEDIA_ASSETS_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    runs = os.environ.get("MASE_RUNS_DIR")
    if runs:
        return (Path(runs).expanduser() / "media_assets").resolve()
    return (_resolve_memory_dir() / "media_assets").resolve()


def _target_path(sha256: str, suffix: str, root: Path) -> Path:
    if not _SUFFIX_RE.fullmatch(suffix or ""):
        raise AssetStoreError(f"非法资产后缀: {suffix!r}")
    target = (root / sha256[:2] / f"{sha256}.{suffix}").resolve()
    if root.resolve() not in target.parents:
        raise AssetStoreError(f"资产写路径越界: {target}")
    return target


def store_bytes(data: bytes, *, suffix: str, root: Path | None = None) -> tuple[str, Path]:
    """按内容哈希存储字节;返回 (sha256, 存储路径)。同哈希已存在则复用。"""
    base = (root or resolve_asset_root()).resolve()
    sha256 = hashlib.sha256(data).hexdigest()
    target = _target_path(sha256, suffix, base)
    if target.exists():
        return sha256, target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)  # 原子落盘,避免半写文件被当成完整资产
    return sha256, target


def asset_path(sha256: str, *, root: Path | None = None) -> Path | None:
    """按哈希定位资产文件;不存在返回 None。"""
    base = (root or resolve_asset_root()).resolve()
    prefix_dir = base / sha256[:2]
    if not prefix_dir.is_dir():
        return None
    for candidate in prefix_dir.glob(f"{sha256}.*"):
        if candidate.is_file() and not candidate.name.endswith(".tmp"):
            return candidate
    return None
