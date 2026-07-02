"""音频抽取器:两段式契约、时间戳 evidence 校验、分块、降级。假转写+假LLM。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.audio_transcriber import TranscriptSegment
from mase.multimodal.document_loader import AudioTrack, MediaPayload
from mase.multimodal.extractor import MediaAssetInfo


class FakeModelInterface:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, agent_type, messages, mode=None, tools=None, override_system_prompt=None, prompt_key="system_prompt"):
        self.calls.append({"agent_type": agent_type, "messages": messages,
                           "override_system_prompt": override_system_prompt})
        return {"message": {"role": "assistant", "content": self.replies.pop(0)}, "model": "fake-llm"}


def _fake_transcribe(segments, info=None):
    def _fn(track, *, model_name, device, compute_type):
        return segments, dict(info or {"language": "zh", "duration_seconds": 9.9,
                                       "model_name": model_name, "device": device,
                                       "compute_type": compute_type, "device_fallback": False,
                                       "beam_size": 5})
    return _fn


def _payload(tmp_path):
    wav = tmp_path / "meet.wav"
    wav.write_bytes(b"RIFF")
    return MediaPayload(audio=AudioTrack(wav, "audio/wav"))


def _asset():
    return MediaAssetInfo(media_id=1, sha256="a" * 64, media_type="audio/wav",
                          source_uri="meet.wav", page_count=0)


def test_extract_transcript_is_full_text_and_facts_carry_timestamps(tmp_path):
    from mase.multimodal.audio_extractor import AudioExtractor

    segs = [TranscriptSegment(0.0, 3.0, "会议开始"), TranscriptSegment(61.0, 65.0, "预算四千二百欧元获批")]
    reply = json.dumps({"facts": [{
        "category": "finance_budget", "key": "meeting_budget", "value": "4200 EUR approved",
        "confidence": 0.9, "evidence": "[00:01:01] 预算四千二百欧元获批"}]})
    fake_llm = FakeModelInterface([reply])
    extractor = AudioExtractor(fake_llm, transcribe_fn=_fake_transcribe(segs))
    result = extractor.extract(_asset(), _payload(tmp_path))

    assert result.full_text == "[00:00:00] 会议开始\n[00:01:01] 预算四千二百欧元获批"
    assert result.extractor_name == "audio" and result.extractor_version == "1"
    assert result.candidate_facts[0].evidence.startswith("[00:01:01]")
    assert result.metadata["asr"]["language"] == "zh"
    assert fake_llm.calls[0]["agent_type"] == "speech_facts"
    assert "[00:00:00]" in fake_llm.calls[0]["messages"][0]["content"]  # 转写稿喂给 LLM
    assert result.warnings == ()
    # model_name 记 "ASR模型+LLM":包含两段的可审计归因
    assert "large-v3" in result.model_name and "fake-llm" in result.model_name


def test_fact_without_timestamp_evidence_kept_with_warning(tmp_path):
    from mase.multimodal.audio_extractor import AudioExtractor

    segs = [TranscriptSegment(0.0, 3.0, "预算获批")]
    reply = json.dumps({"facts": [{"category": "finance_budget", "key": "b", "value": "approved",
                                   "confidence": 0.5, "evidence": "预算获批"}]})
    extractor = AudioExtractor(FakeModelInterface([reply]), transcribe_fn=_fake_transcribe(segs))
    result = extractor.extract(_asset(), _payload(tmp_path))
    assert len(result.candidate_facts) == 1  # 保留
    assert any("evidence missing timestamp" in w for w in result.warnings)


def test_long_transcript_chunked_at_segment_boundaries(tmp_path):
    from mase.multimodal import audio_extractor
    from mase.multimodal.audio_extractor import AudioExtractor

    segs = [TranscriptSegment(float(i), float(i) + 0.5, "长" * 50) for i in range(10)]
    # 每行 "[00:00:0i] " + 50 字 = 62 字符(含换行);300 上限 → 4+4+2 = 3 块
    replies = [json.dumps({"facts": []})] * 3
    fake_llm = FakeModelInterface(replies)
    extractor = AudioExtractor(fake_llm, transcribe_fn=_fake_transcribe(segs))
    orig = audio_extractor.TRANSCRIPT_CHUNK_CHARS
    audio_extractor.TRANSCRIPT_CHUNK_CHARS = 300
    try:
        result = extractor.extract(_asset(), _payload(tmp_path))
    finally:
        audio_extractor.TRANSCRIPT_CHUNK_CHARS = orig
    assert len(fake_llm.calls) == 3
    assert "chunked: 3 parts" in result.warnings
    # 每块都是完整行(segment 边界),不劈开单段
    for call in fake_llm.calls:
        for line in call["messages"][0]["content"].splitlines():
            assert line.startswith("[")


def test_malformed_llm_reply_degrades_to_transcript_only(tmp_path):
    from mase.multimodal.audio_extractor import AudioExtractor

    segs = [TranscriptSegment(0.0, 3.0, "内容")]
    # 两条坏回复:纠正性重试一次后仍失败 → 降级为仅转写稿
    extractor = AudioExtractor(FakeModelInterface(["not json", "still bad"]), transcribe_fn=_fake_transcribe(segs))
    result = extractor.extract(_asset(), _payload(tmp_path))
    assert result.full_text == "[00:00:00] 内容"  # 转写稿完整保留
    assert result.candidate_facts == ()
    assert any("non_json_response" in w for w in result.warnings)


def test_supports_only_audio(tmp_path):
    from mase.multimodal.audio_extractor import AudioExtractor

    extractor = AudioExtractor(FakeModelInterface([]), transcribe_fn=_fake_transcribe([]))
    assert extractor.supports("audio/wav") and extractor.supports("audio/mpeg")
    assert not extractor.supports("image/png") and not extractor.supports("application/pdf")


def test_speech_facts_agent_configured():
    config = json.load(open(_ROOT / "config.json", encoding="utf-8"))
    agent = config["models"]["speech_facts"]
    assert agent["provider"] == "ollama"
    assert agent["model_name"] == "qwen2.5:7b"
    assert agent["temperature"] == 0.0
