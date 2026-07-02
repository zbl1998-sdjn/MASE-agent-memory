"""文档 → 页图序列。

图像文件直通(1 页,保留原字节与 MIME);PDF 经 PyMuPDF 按页栅格化为
PNG 字节。PyMuPDF 是可选依赖:核心安装不带,缺失时给出明确安装指引,
不静默降级。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class MissingDependencyError(Exception):
    """可选依赖缺失;消息包含安装指引。"""


@dataclass(frozen=True)
class PageImage:
    """单页图像:index 从 0 起;image_bytes 为该页完整图像字节。"""

    index: int
    image_bytes: bytes
    media_type: str


def load_pages(path: Path, media_type: str, *, pdf_dpi: int = 150) -> list[PageImage]:
    """把一个已过安全检查的文件转成页图列表。

    pdf_dpi 默认 150:文档 OCR 可读性与 VLM token 成本的折中;验收
    harness 会把实际 DPI 记入证据文件。
    """
    if media_type == "application/pdf":
        return _load_pdf_pages(Path(path), dpi=pdf_dpi)
    return [PageImage(index=0, image_bytes=Path(path).read_bytes(), media_type=media_type)]


def _load_pdf_pages(path: Path, *, dpi: int) -> list[PageImage]:
    try:
        import fitz  # PyMuPDF,按需导入:核心路径不背 PDF 依赖
    except ImportError as exc:
        raise MissingDependencyError(
            "解析 PDF 需要 PyMuPDF。请安装: pip install \"mase-memory[multimodal]\" "
            "或 pip install \"pymupdf>=1.24,<2.0\""
        ) from exc

    pages: list[PageImage] = []
    with fitz.open(str(path)) as doc:
        for page_index, page in enumerate(doc):
            pixmap = page.get_pixmap(dpi=dpi)
            pages.append(
                PageImage(index=page_index, image_bytes=pixmap.tobytes("png"), media_type="image/png")
            )
    return pages
