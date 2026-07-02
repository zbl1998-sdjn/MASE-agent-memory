"""provider 感知图像消息:三家序列化形状 + 未知 provider 拒绝。"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.document_loader import PageImage

_PAGE = PageImage(0, b"\x89PNGfake", "image/png")
_B64 = base64.b64encode(b"\x89PNGfake").decode("ascii")


def test_ollama_shape_images_sibling_field():
    from mase.multimodal.image_message import build_image_message

    msg = build_image_message("ollama", "请抽取", _PAGE)
    assert msg == {"role": "user", "content": "请抽取", "images": [_B64]}


def test_openai_shape_data_uri_blocks():
    from mase.multimodal.image_message import build_image_message

    msg = build_image_message("openai", "extract", _PAGE)
    assert msg["role"] == "user"
    assert msg["content"][0] == {"type": "text", "text": "extract"}
    assert msg["content"][1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{_B64}"},
    }


def test_anthropic_shape_image_before_text():
    from mase.multimodal.image_message import build_image_message

    msg = build_image_message("anthropic", "extract", _PAGE)
    assert msg["role"] == "user"
    # Anthropic 官方最佳实践:图在前文在后
    assert msg["content"][0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": _B64},
    }
    assert msg["content"][1] == {"type": "text", "text": "extract"}


def test_unknown_provider_rejected():
    from mase.multimodal.image_message import build_image_message

    with pytest.raises(ValueError, match="llama_cpp"):
        build_image_message("llama_cpp", "p", _PAGE)
