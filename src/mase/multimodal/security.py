"""摄取安全边界:路径 jail + 媒体类型/大小 allowlist。

S0 只读本地文件,不做 URL 抓取(无 SSRF 面);所有文件访问先过
assert_within_jail,再过 classify_media,两道都过才进入抽取管线。
"""
from __future__ import annotations

from pathlib import Path

ALLOWED_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
}

DEFAULT_MAX_BYTES = 50 * 1024 * 1024   # 图像/文档单文件上限
AUDIO_MAX_BYTES = 500 * 1024 * 1024    # 音频单文件上限:1 小时会议 mp3 常超 50MB


def default_max_bytes(media_type: str) -> int:
    """按媒体类型给默认大小上限(读模块属性,测试可 monkeypatch)。"""
    return AUDIO_MAX_BYTES if media_type.startswith("audio/") else DEFAULT_MAX_BYTES


class IngestSecurityError(Exception):
    """摄取安全边界拒绝(基类)。"""


class JailViolation(IngestSecurityError):
    """路径越出 allowed_root(含符号链接/.. 逃逸)。"""


class UnsupportedMedia(IngestSecurityError):
    """媒体类型不在 allowlist 或超出大小上限。"""


def assert_within_jail(path: Path, allowed_root: Path) -> Path:
    """resolve 后断言 path 位于 allowed_root 之内,返回归一化路径。

    resolve() 同时消解符号链接与 ``..``,因此链接指向根外也会被拒。
    """
    resolved = Path(path).resolve()
    root = Path(allowed_root).resolve()
    if resolved != root and root not in resolved.parents:
        raise JailViolation(f"路径越界: {resolved} 不在 {root} 之内")
    return resolved


def classify_media(path: Path, *, max_bytes: int | None = None) -> str:
    """按扩展名 allowlist 归类媒体类型;非白名单或超限抛 UnsupportedMedia。

    max_bytes=None 时按类型取默认上限(图像/文档 50MB、音频 500MB);
    显式传值则全类型统一(旧行为,CLI --max-mb 用)。
    """
    suffix = Path(path).suffix.lower()
    media_type = ALLOWED_MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise UnsupportedMedia(f"不支持的媒体类型: {suffix!r} ({path})")
    effective_max = max_bytes if max_bytes is not None else default_max_bytes(media_type)
    size = Path(path).stat().st_size
    if size > effective_max:
        raise UnsupportedMedia(f"文件超过大小上限 {effective_max}B: {path} ({size}B)")
    return media_type
