"""视觉抽取器 v8:近空首轮转写的重转写恢复(轮五取证驱动)。

轮五诊断实录(xfund_diag_20260711T0300Z,zh_train_43):VLM 首轮只回了
"Video:来源:zh_train_43.jpg第1/1页。"(复述 prompt 页眉,30 字符,正文
零转写)——page_text 非空所以补看轮照走,但补看救不回整页丢失,最终
0/5 事实、零警告。修复契约:

- 首轮转写实质内容 < 阈值(近空)→ 用同一忠实转写 prompt 重转写一次
  (不用"补缺失"prompt:对空底稿它语义畸形且诱导编造);
- 重转写有实质产出 → 采用,warning 记 vision_retranscribe_recovered;
- 重转写仍近空 → 保留较长一版,warning 记 vision_page_near_empty
  (真空白页两轮都空,零产出语义与 halluc_ok 护栏不变,失败首次可见);
- 首轮正常(≥阈值)→ 行为与 v7 逐字节一致,不多调用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.document_loader import MediaPayload, PageImage
from mase.multimodal.extractor import MediaAssetInfo


class FakeModelInterface:
    provider = "ollama"

    def __init__(self, transcripts=None, facts_replies=None):
        self.transcripts = list(transcripts or [])
        self.facts_replies = list(facts_replies or [])
        self.calls = []

    def get_effective_agent_config(self, agent_type, mode=None):
        return {"provider": self.provider, "model_name": "fake-vlm"}

    def chat(self, agent_type, messages, mode=None, tools=None, override_system_prompt=None, prompt_key="system_prompt"):
        self.calls.append({
            "agent_type": agent_type,
            "override_system_prompt": override_system_prompt,
        })
        if agent_type == "vision":
            return {"message": {"role": "assistant", "content": self.transcripts.pop(0)}, "model": "fake-vlm"}
        return {"message": {"role": "assistant", "content": self.facts_replies.pop(0)}, "model": "fake-llm"}


def _asset():
    return MediaAssetInfo(media_id=1, sha256="a" * 64, media_type="image/png", source_uri="s.png", page_count=1)


def _payload():
    return MediaPayload(pages=(PageImage(0, b"\x89PNGfake", "image/png"),))


_REAL_TEXT = "共同申请人3 姓名 郜高玺 身份证号码 652327197811173193 婚姻 已婚 联系电话 13900000000"


def test_near_empty_first_pass_recovers_via_retranscribe():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(
        # 首轮:复述页眉(近空)→ 重转写:真实正文 → 补看:无缺失
        transcripts=["Video:来源:s.png第1/1页。", _REAL_TEXT, "无缺失"],
        facts_replies=[json.dumps({"facts": []}), "无事实"],
    )
    result = VisionExtractor(fake).extract(_asset(), _payload())

    assert "郜高玺" in result.full_text
    assert any("vision_retranscribe_recovered" in w for w in result.warnings)
    # 重转写用的是同一套忠实转写 system prompt,不是补缺失 prompt。
    vision_calls = [c for c in fake.calls if c["agent_type"] == "vision"]
    assert len(vision_calls) == 3  # 转写 + 重转写 + 补看
    assert "转写" in vision_calls[1]["override_system_prompt"]
    assert "缺失" not in vision_calls[1]["override_system_prompt"]


def test_double_near_empty_is_flagged_but_not_hallucinated():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(
        transcripts=["", ""],  # 真空白页:两轮都空
        facts_replies=["无事实", "无事实"],
    )
    result = VisionExtractor(fake).extract(_asset(), _payload())

    assert result.candidate_facts == ()  # 零产出语义保持(halluc_ok)
    assert any("vision_page_near_empty" in w for w in result.warnings)
    vision_calls = [c for c in fake.calls if c["agent_type"] == "vision"]
    assert len(vision_calls) == 2  # 转写 + 重转写;空文本不走补看轮


def test_near_empty_keeps_longer_variant_when_both_short():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(
        # 两轮都 < 阈值,第二轮较长;保留的短文本非空仍走补看轮
        transcripts=["页眉。", "表单编号 A-1", "无缺失"],
        facts_replies=["无事实", "无事实"],
    )
    result = VisionExtractor(fake).extract(_asset(), _payload())
    assert "表单编号 A-1" in result.full_text
    assert any("vision_page_near_empty" in w for w in result.warnings)


def test_normal_first_pass_behavior_unchanged():
    from mase.multimodal.vision_extractor import VisionExtractor

    normal_text = "申请表 姓名 张三 出生日期 1990-01-01 学历 本科 单位 蓝天贸易有限公司"
    fake = FakeModelInterface(
        transcripts=[normal_text, "无缺失"],
        facts_replies=[json.dumps({"facts": []}), "无事实"],
    )
    result = VisionExtractor(fake).extract(_asset(), _payload())

    assert result.full_text == normal_text
    vision_calls = [c for c in fake.calls if c["agent_type"] == "vision"]
    assert len(vision_calls) == 2  # 转写 + 补看;不触发重转写
    assert not any("retranscribe" in w for w in result.warnings)
