"""瞬时基础设施错误重试(GPU 高压下 ollama 偶发 CUDA 5xx,整例白丢太贵)。

口径:只对"瞬时 infra"类错误(CUDA error / server 5xx)重试一次并留 warning;
业务/配置错误原样抛。这是抽取管线容错,不是评测按例重试(runner 口径不变)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_retries_once_on_cuda_error():
    from mase.multimodal.transient_retry import call_with_transient_retry

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("an error was encountered while running the model: CUDA error: an illegal memory access was encountered")
        return "ok"

    warnings: list[str] = []
    assert call_with_transient_retry(flaky, warnings=warnings, sleep_seconds=0) == "ok"
    assert calls["n"] == 2
    assert any(w.startswith("transient_infra_retry") for w in warnings)


def test_retries_once_on_500_status():
    from mase.multimodal.transient_retry import call_with_transient_retry

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ResponseError: something broke (status code: 500)")
        return 42

    assert call_with_transient_retry(flaky, warnings=[], sleep_seconds=0) == 42


def test_non_transient_error_is_not_retried():
    from mase.multimodal.transient_retry import call_with_transient_retry

    calls = {"n": 0}

    def bad_config():
        calls["n"] += 1
        raise ValueError("model not configured")

    with pytest.raises(ValueError):
        call_with_transient_retry(bad_config, warnings=[], sleep_seconds=0)
    assert calls["n"] == 1


def test_double_failure_raises_last_error():
    from mase.multimodal.transient_retry import call_with_transient_retry

    def always_cuda():
        raise RuntimeError("CUDA error: unknown error (status code: 500)")

    warnings: list[str] = []
    with pytest.raises(RuntimeError):
        call_with_transient_retry(always_cuda, warnings=warnings, sleep_seconds=0)
    assert any(w.startswith("transient_infra_retry") for w in warnings)


def test_vision_transcription_survives_one_cuda_hiccup():
    # 端到端:VLM 第一次调用炸 CUDA,第二次成功 → 抽取正常完成。
    import base64  # noqa: F401
    from mase.multimodal.document_loader import MediaPayload, PageImage
    from mase.multimodal.extractor import MediaAssetInfo
    from mase.multimodal.vision_extractor import VisionExtractor

    class FlakyModel:
        provider = "ollama"

        def __init__(self):
            self.vision_calls = 0

        def get_effective_agent_config(self, agent_type, mode=None):
            return {"provider": self.provider, "model_name": "fake"}

        def chat(self, agent_type, messages, mode=None, tools=None, override_system_prompt=None, prompt_key="system_prompt"):
            if agent_type == "vision":
                self.vision_calls += 1
                if self.vision_calls == 1:
                    raise RuntimeError("CUDA error: an illegal memory access was encountered (status code: 500)")
                return {"message": {"role": "assistant", "content": "TOTAL 15.00"}, "model": "fake-vlm"}
            return {"message": {"role": "assistant", "content": "无事实"}, "model": "fake-llm"}

    fake = FlakyModel()
    asset = MediaAssetInfo(media_id=1, sha256="a" * 64, media_type="image/png", source_uri="s.png", page_count=1)
    payload = MediaPayload(pages=[PageImage(0, b"png", "image/png")], audio=None)
    result = VisionExtractor(fake).extract(asset, payload)
    assert result.full_text == "TOTAL 15.00"
    assert any(w.startswith("transient_infra_retry") for w in result.warnings)
