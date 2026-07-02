"""文档加载器:图像直通、PDF 按页栅格化、缺依赖有明确报错。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_image_passthrough_single_page(tmp_path):
    from mase.multimodal.document_loader import load_pages

    img = tmp_path / "shot.jpg"
    img.write_bytes(b"\xff\xd8fakejpeg")
    pages = load_pages(img, "image/jpeg")
    assert len(pages) == 1
    assert pages[0].index == 0
    assert pages[0].image_bytes == b"\xff\xd8fakejpeg"
    assert pages[0].media_type == "image/jpeg"


def test_pdf_rasterizes_each_page(tmp_path):
    fitz = pytest.importorskip("fitz")  # PyMuPDF;dev extra 已含,环境缺失时跳过
    from mase.multimodal.document_loader import load_pages

    doc = fitz.open()
    for text in ("Page one: invoice #001", "Page two: total 4200 EUR"):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    pdf = tmp_path / "two.pdf"
    doc.save(str(pdf))
    doc.close()

    pages = load_pages(pdf, "application/pdf")
    assert [p.index for p in pages] == [0, 1]
    assert all(p.media_type == "image/png" for p in pages)
    assert all(p.image_bytes[:8] == b"\x89PNG\r\n\x1a\n" for p in pages)


def test_missing_pymupdf_gives_actionable_error(tmp_path, monkeypatch):
    import builtins

    from mase.multimodal import document_loader
    from mase.multimodal.document_loader import MissingDependencyError

    real_import = builtins.__import__

    def _no_fitz(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("No module named 'fitz'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_fitz)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(MissingDependencyError, match=r"mase-memory\[multimodal\]"):
        document_loader.load_pages(pdf, "application/pdf")
