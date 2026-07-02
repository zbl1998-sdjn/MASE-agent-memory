"""VLM 视觉抽取器:Ollama images 传参形状、JSON 解析、降级、多页聚合。"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.document_loader import MediaPayload, PageImage
from mase.multimodal.extractor import MediaAssetInfo


def _pages(*page_images):
    """接缝演化后的调用形状:pages 走 MediaPayload;断言不变。"""
    return MediaPayload(pages=tuple(page_images))


class FakeModelInterface:
    """记录 chat() 入参并按序返回预置响应。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, agent_type, messages, mode=None, tools=None, override_system_prompt=None, prompt_key="system_prompt"):
        self.calls.append({
            "agent_type": agent_type, "messages": messages, "mode": mode,
            "override_system_prompt": override_system_prompt,
        })
        return {"message": {"role": "assistant", "content": self.replies.pop(0)}, "model": "fake-vlm"}


def _asset(pages=1):
    return MediaAssetInfo(media_id=1, sha256="a" * 64, media_type="image/png", source_uri="s.png", page_count=pages)


def test_extract_sends_base64_images_sibling_field_and_parses_json():
    from mase.multimodal.vision_extractor import VisionExtractor

    reply = json.dumps({
        "full_text": "Invoice #001 total 4200 EUR",
        "facts": [{"category": "finance_budget", "key": "invoice_001_total",
                   "value": "4200 EUR", "confidence": 0.9, "evidence": "total 4200 EUR"}],
    })
    fake = FakeModelInterface([reply])
    extractor = VisionExtractor(fake)
    page_bytes = b"\x89PNGfake"
    result = extractor.extract(_asset(), _pages(PageImage(0, page_bytes, "image/png")))

    call = fake.calls[0]
    assert call["agent_type"] == "vision"
    user_msg = call["messages"][0]
    assert user_msg["role"] == "user"
    assert user_msg["images"] == [base64.b64encode(page_bytes).decode("ascii")]  # Ollama 兄弟字段,裸 base64
    assert call["override_system_prompt"]  # 抽取契约提示词与解析器同处一模块

    assert result.full_text == "Invoice #001 total 4200 EUR"
    assert result.candidate_facts[0].key == "invoice_001_total"
    assert result.model_name == "fake-vlm"
    assert result.extractor_name == "vision" and result.extractor_version == "1"
    assert result.warnings == ()


def test_malformed_json_degrades_to_full_text_with_warning():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(["The image shows an invoice, not JSON at all."])
    result = VisionExtractor(fake).extract(_asset(), _pages(PageImage(0, b"img", "image/png")))
    assert "invoice" in result.full_text
    assert result.candidate_facts == ()
    assert any("non_json_response" in w for w in result.warnings)


def test_multipage_aggregates_text_and_facts_in_order():
    from mase.multimodal.vision_extractor import VisionExtractor

    replies = [
        json.dumps({"full_text": "page one text", "facts": [
            {"category": "general_facts", "key": "k1", "value": "v1", "confidence": 0.5, "evidence": "e1"}]}),
        json.dumps({"full_text": "page two text", "facts": [
            {"category": "general_facts", "key": "k2", "value": "v2", "confidence": 0.5, "evidence": "e2"}]}),
    ]
    fake = FakeModelInterface(replies)
    result = VisionExtractor(fake).extract(
        _asset(pages=2),
        _pages(PageImage(0, b"p1", "image/png"), PageImage(1, b"p2", "image/png")),
    )
    assert len(fake.calls) == 2  # 每页一次调用,7B VLM 单图更可靠
    assert "page one text" in result.full_text and "page two text" in result.full_text
    assert result.full_text.index("page one") < result.full_text.index("page two")
    assert "--- page 2 ---" in result.full_text
    assert [f.key for f in result.candidate_facts] == ["k1", "k2"]


def test_mode_passthrough_for_model_switch():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface([json.dumps({"full_text": "t", "facts": []})])
    VisionExtractor(fake, mode="minicpm").extract(_asset(), _pages(PageImage(0, b"i", "image/png")))
    assert fake.calls[0]["mode"] == "minicpm"


def test_supports_matrix():
    from mase.multimodal.vision_extractor import VisionExtractor

    extractor = VisionExtractor(FakeModelInterface([]))
    assert extractor.supports("image/png") and extractor.supports("application/pdf")
    assert not extractor.supports("audio/wav")


def test_vision_agent_configured_in_config_json():
    """配置契约钉:vision agent 存在,默认 qwen2.5vl:7b,minicpm mode 可切换。"""
    import json as _json

    config = _json.load(open(_ROOT / "config.json", encoding="utf-8"))
    vision = config["models"]["vision"]
    assert vision["provider"] == "ollama"
    assert vision["model_name"] == "qwen2.5vl:7b"
    assert vision["modes"]["minicpm"]["model_name"] == "minicpm-v4.5"
