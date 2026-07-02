"""provider 感知的图像消息构造器(引擎无关接缝的序列化端)。

三家请求体差异(2026-07 官方文档核验):
- ollama:  message 级 ``images: [<裸base64>]`` 兄弟字段(docs/api.md)
- openai:  content blocks ``image_url`` + data URI(developers.openai.com)
- anthropic: content blocks ``image`` source,图前文后(platform.claude.com vision)
云 provider 的实际调用仍经 model_interface 的云审批门控,这里只管形状。
"""
from __future__ import annotations

import base64
from typing import Any

from .document_loader import PageImage


def build_image_message(provider: str, prompt: str, page: PageImage) -> dict[str, Any]:
    """把"提示词 + 单页图"序列化成目标 provider 的 user 消息。"""
    b64 = base64.b64encode(page.image_bytes).decode("ascii")
    normalized = str(provider or "").strip().lower()
    if normalized == "ollama":
        return {"role": "user", "content": prompt, "images": [b64]}
    if normalized == "openai":
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{page.media_type};base64,{b64}"}},
            ],
        }
    if normalized == "anthropic":
        return {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": page.media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }
    raise ValueError(f"不支持的视觉 provider: {provider!r}(支持 ollama/openai/anthropic)")
