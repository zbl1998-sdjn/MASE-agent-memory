"""VLM 视觉抽取器 v2(两段式):转写段传参形状、事实段契约、降级、多页聚合。"""
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
    return MediaPayload(pages=tuple(page_images))


class FakeModelInterface:
    """按 agent_type 路由:vision → 转写文本;doc_facts → 事实 JSON。"""

    provider = "ollama"

    def __init__(self, transcripts=None, facts_replies=None):
        self.transcripts = list(transcripts or [])
        self.facts_replies = list(facts_replies or [])
        self.calls = []

    def get_effective_agent_config(self, agent_type, mode=None):
        return {"provider": self.provider, "model_name": "fake-vlm"}

    def chat(self, agent_type, messages, mode=None, tools=None, override_system_prompt=None, prompt_key="system_prompt"):
        self.calls.append({
            "agent_type": agent_type, "messages": messages, "mode": mode,
            "override_system_prompt": override_system_prompt,
        })
        if agent_type == "vision":
            return {"message": {"role": "assistant", "content": self.transcripts.pop(0)}, "model": "fake-vlm"}
        return {"message": {"role": "assistant", "content": self.facts_replies.pop(0)}, "model": "fake-llm"}


def _asset(pages=1):
    return MediaAssetInfo(media_id=1, sha256="a" * 64, media_type="image/png", source_uri="s.png", page_count=pages)


def _facts_reply():
    return json.dumps({"facts": [{"category": "finance_budget", "key": "invoice_total",
                                  "value": "4200 EUR", "confidence": 0.9, "evidence": "total 4200 EUR"}]})


def test_two_stage_transcribe_then_extract_facts():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(
        transcripts=["Invoice #001 total 4200 EUR"],
        facts_replies=[_facts_reply()],
    )
    page_bytes = b"\x89PNGfake"
    result = VisionExtractor(fake).extract(_asset(), _pages(PageImage(0, page_bytes, "image/png")))

    # 第一段:VLM 只转写(Ollama images 兄弟字段,裸 base64)
    stage1 = fake.calls[0]
    assert stage1["agent_type"] == "vision"
    assert stage1["messages"][0]["images"] == [base64.b64encode(page_bytes).decode("ascii")]
    assert "转写" in stage1["override_system_prompt"]
    # 第二段:文本 LLM 从全文抽事实,输入含转写稿
    stage2 = fake.calls[1]
    assert stage2["agent_type"] == "doc_facts"
    assert "Invoice #001" in stage2["messages"][0]["content"]

    assert result.full_text == "Invoice #001 total 4200 EUR"
    assert result.candidate_facts[0].key == "invoice_total"
    assert result.extractor_name == "vision" and result.extractor_version == "2"
    # 两段归因:VLM + 事实 LLM
    assert "fake-vlm" in result.model_name and "fake-llm" in result.model_name
    assert result.warnings == ()


def test_multipage_transcripts_aggregate_before_single_fact_pass():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(
        transcripts=["page one text", "page two text"],
        facts_replies=[json.dumps({"facts": []})],
    )
    result = VisionExtractor(fake).extract(
        _asset(pages=2),
        _pages(PageImage(0, b"p1", "image/png"), PageImage(1, b"p2", "image/png")),
    )
    vision_calls = [c for c in fake.calls if c["agent_type"] == "vision"]
    facts_calls = [c for c in fake.calls if c["agent_type"] == "doc_facts"]
    assert len(vision_calls) == 2  # 每页一次转写
    assert len(facts_calls) == 1   # 全文聚合后一次抽取(短文本单块)
    assert "page one text" in result.full_text and "page two text" in result.full_text
    assert "--- page 2 ---" in result.full_text
    assert "page one text" in facts_calls[0]["messages"][0]["content"]
    assert "page two text" in facts_calls[0]["messages"][0]["content"]


def test_malformed_facts_reply_degrades_to_transcript_only():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(transcripts=["The invoice text"], facts_replies=["not json"])
    result = VisionExtractor(fake).extract(_asset(), _pages(PageImage(0, b"img", "image/png")))
    assert "invoice" in result.full_text
    assert result.candidate_facts == ()
    assert any("non_json_response" in w for w in result.warnings)


def test_mode_passthrough_for_model_switch():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(transcripts=["t"], facts_replies=[json.dumps({"facts": []})])
    VisionExtractor(fake, mode="minicpm").extract(_asset(), _pages(PageImage(0, b"i", "image/png")))
    vision_call = [c for c in fake.calls if c["agent_type"] == "vision"][0]
    assert vision_call["mode"] == "minicpm"


def test_supports_matrix():
    from mase.multimodal.vision_extractor import VisionExtractor

    extractor = VisionExtractor(FakeModelInterface())
    assert extractor.supports("image/png") and extractor.supports("application/pdf")
    assert not extractor.supports("audio/wav")


def test_openai_provider_builds_content_blocks():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(transcripts=["t"], facts_replies=[json.dumps({"facts": []})])
    fake.provider = "openai"
    VisionExtractor(fake).extract(_asset(), _pages(PageImage(0, b"i", "image/png")))
    content = [c for c in fake.calls if c["agent_type"] == "vision"][0]["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_agents_configured_in_config_json():
    """配置契约钉:vision 双模型 + doc_facts 事实段 agent 存在。"""
    config = json.load(open(_ROOT / "config.json", encoding="utf-8"))
    vision = config["models"]["vision"]
    assert vision["provider"] == "ollama"
    assert vision["model_name"] == "qwen2.5vl:7b"
    assert vision["modes"]["minicpm"]["model_name"] == "minicpm-v4.5"
    doc_facts = config["models"]["doc_facts"]
    assert doc_facts["provider"] == "ollama"
    assert doc_facts["model_name"] == "qwen2.5:7b"
    assert doc_facts["temperature"] == 0.0
