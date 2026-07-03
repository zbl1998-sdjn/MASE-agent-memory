"""音频抽取器(S1 第二段:转写稿 → 文本 LLM 抽时间线事实)。

两段式白盒:转写稿(audit 底稿)由 audio_transcriber 生成并完整入
full_text;事实抽取用现有 Ollama 文本模型(config `speech_facts`),
严格 JSON 契约与 S0 视觉一致,另要求 evidence 引用带 [HH:MM:SS] 的
原文行 → 每条事实自带时间线锚点。畸形回复降级为"仅转写稿",绝不抛穿。
"""
from __future__ import annotations

from typing import Any

from .audio_transcriber import (
    format_transcript,
    resolve_whisper_settings,
    transcribe,
)
from .document_loader import MediaPayload
from .extractor import ExtractionResult, MediaAssetInfo
from .text_facts import extract_facts_from_text

AUDIO_EXTRACTOR_VERSION = "2"
TRANSCRIPT_CHUNK_CHARS = 6000  # 超过则按 segment 行边界分块抽取(spec §5)

SPEECH_FACTS_SYSTEM = """你是会议纪要事实抽取器。输入是带 [HH:MM:SS] 时间戳的会议/语音转写稿。
每找到一条事实,就输出一行,格式(用竖线分隔的四段):
category | key | value | evidence

- category 取以下之一:user_preferences、people_relations、project_status、finance_budget、location_events、general_facts
- key 用 snake_case 唯一键;value 是事实当前值
- evidence 必须逐字引用转写稿的整行(含 [HH:MM:SS] 时间戳前缀)
- 除了事实行,不要输出任何其他文字;没有事实就只输出一行:无事实

抽取规则:
- 只提取转写稿中明确说出的决策、待办、承诺、预算、时间安排等事实,不要推测;
- value 逐字取自原文,不改写格式。"""


class AudioExtractor:
    """把音频资产转成"转写稿 + 时间线事实"的可审计 ExtractionResult。"""

    name = "audio"
    version = AUDIO_EXTRACTOR_VERSION

    def __init__(
        self,
        model_interface: Any = None,
        *,
        whisper_model: str | None = None,
        transcribe_fn: Any = None,
    ) -> None:
        if model_interface is None:
            from mase.model_interface import ModelInterface

            model_interface = ModelInterface()
        self.model_interface = model_interface
        self.whisper_settings = resolve_whisper_settings(whisper_model)
        # 依赖注入点:测试注入确定性假转写;生产走真 faster-whisper。
        self._transcribe = transcribe_fn or transcribe

    def supports(self, media_type: str) -> bool:
        return media_type.startswith("audio/")

    def extract(self, asset: MediaAssetInfo, payload: MediaPayload) -> ExtractionResult:
        if payload.audio is None:
            raise ValueError(f"AudioExtractor 需要 audio payload,got pages={len(payload.pages)}")

        segments, info = self._transcribe(
            payload.audio,
            model_name=self.whisper_settings["model_name"],
            device=self.whisper_settings["device"],
            compute_type=self.whisper_settings["compute_type"],
        )
        full_text = format_transcript(segments)

        # 第二段走公共 text_facts(与视觉 v2 同一执行点);
        # 时间戳 evidence 校验是音频特有契约,在事实返回后补充。
        facts, warnings, llm_model = extract_facts_from_text(
            self.model_interface,
            agent_type="speech_facts",
            system_prompt=SPEECH_FACTS_SYSTEM,
            text=full_text,
            chunk_chars=TRANSCRIPT_CHUNK_CHARS,
        )
        warnings = list(warnings)
        for fact in facts:
            if not fact.evidence.startswith("["):
                warnings.append(f"fact {fact.key}: evidence missing timestamp")

        return ExtractionResult(
            full_text=full_text,
            candidate_facts=tuple(facts),
            extractor_name=self.name,
            # 两段归因:ASR 模型 + 事实抽取 LLM 一起写进 model_name,审计可见
            model_name=f"{info.get('model_name', 'unknown')}+{llm_model}",
            extractor_version=self.version,
            warnings=tuple(warnings),
            metadata={"asr": info},
        )
