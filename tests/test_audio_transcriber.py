"""转写器:时间戳格式、env 解析、cuda 回退、缺依赖报错。全部假模型。"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.document_loader import AudioTrack


class _FakeSeg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class _FakeInfo:
    language = "zh"
    duration = 63.2


def _install_fake_faster_whisper(monkeypatch, *, fail_on_device: str | None = None, created: list | None = None):
    module = types.ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, model_name, device="cpu", compute_type="default"):
            if fail_on_device and device == fail_on_device:
                raise RuntimeError("CUDA driver not found (simulated)")
            self.args = (model_name, device, compute_type)
            if created is not None:
                created.append(self.args)

        def transcribe(self, path, beam_size=None, temperature=None):
            assert beam_size == 5 and temperature == 0.0  # 确定性参数钉死
            return iter([_FakeSeg(0.0, 2.5, " 会议开始 "), _FakeSeg(61.0, 63.2, "预算通过")]), _FakeInfo()

    module.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return module


def test_format_transcript_hhmmss():
    from mase.multimodal.audio_transcriber import TranscriptSegment, format_transcript

    text = format_transcript([
        TranscriptSegment(0.0, 2.5, "会议开始"),
        TranscriptSegment(61.0, 63.2, "预算通过"),
        TranscriptSegment(3661.9, 3670.0, "散会"),
    ])
    assert text.splitlines() == [
        "[00:00:00] 会议开始",
        "[00:01:01] 预算通过",
        "[01:01:01] 散会",
    ]


def test_resolve_whisper_settings_priority(monkeypatch):
    from mase.multimodal.audio_transcriber import resolve_whisper_settings

    for key in ("MASE_WHISPER_MODEL", "MASE_WHISPER_DEVICE", "MASE_WHISPER_COMPUTE"):
        monkeypatch.delenv(key, raising=False)
    assert resolve_whisper_settings() == {"model_name": "large-v3", "device": "cuda", "compute_type": "float16"}

    monkeypatch.setenv("MASE_WHISPER_MODEL", "large-v3-turbo")
    monkeypatch.setenv("MASE_WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("MASE_WHISPER_COMPUTE", "int8")
    assert resolve_whisper_settings() == {"model_name": "large-v3-turbo", "device": "cpu", "compute_type": "int8"}
    assert resolve_whisper_settings("large-v3")["model_name"] == "large-v3"  # 显式覆盖 > env


def test_transcribe_returns_segments_and_info(tmp_path, monkeypatch):
    _install_fake_faster_whisper(monkeypatch)
    from mase.multimodal import audio_transcriber
    audio_transcriber._MODEL_CACHE.clear()
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    segments, info = audio_transcriber.transcribe(
        AudioTrack(wav, "audio/wav"), model_name="large-v3", device="cpu", compute_type="int8",
    )
    assert [s.text for s in segments] == ["会议开始", "预算通过"]  # 文本 strip
    assert info["language"] == "zh" and info["duration_seconds"] == 63.2
    assert info["model_name"] == "large-v3" and info["device_fallback"] is False


def test_transcribe_cuda_failure_falls_back_to_cpu(tmp_path, monkeypatch):
    created: list = []
    _install_fake_faster_whisper(monkeypatch, fail_on_device="cuda", created=created)
    from mase.multimodal import audio_transcriber
    audio_transcriber._MODEL_CACHE.clear()
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    _, info = audio_transcriber.transcribe(
        AudioTrack(wav, "audio/wav"), model_name="large-v3", device="cuda", compute_type="float16",
    )
    assert info["device_fallback"] is True
    assert created[-1] == ("large-v3", "cpu", "int8")


def test_model_instance_cached_per_settings(tmp_path, monkeypatch):
    created: list = []
    _install_fake_faster_whisper(monkeypatch, created=created)
    from mase.multimodal import audio_transcriber
    audio_transcriber._MODEL_CACHE.clear()
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    track = AudioTrack(wav, "audio/wav")
    audio_transcriber.transcribe(track, model_name="large-v3", device="cpu", compute_type="int8")
    audio_transcriber.transcribe(track, model_name="large-v3", device="cpu", compute_type="int8")
    assert len(created) == 1  # 批处理不重复建模


def test_nvidia_dll_dirs_registered_when_present(tmp_path, monkeypatch):
    """pip 安装的 nvidia wheels 的 bin 目录需显式 add_dll_directory(Windows)。"""
    import site

    from mase.multimodal import audio_transcriber

    nvidia = tmp_path / "site" / "nvidia"
    for pkg in ("cublas", "cudnn"):
        (nvidia / pkg / "bin").mkdir(parents=True)
        (nvidia / pkg / "bin" / f"{pkg}64_12.dll").write_bytes(b"x")
    (nvidia / "empty_pkg").mkdir()  # 无 bin 的包不应报错

    monkeypatch.setattr(site, "getsitepackages", lambda: [str(tmp_path / "site")])
    registered: list[str] = []
    monkeypatch.setattr(audio_transcriber.os, "add_dll_directory", registered.append, raising=False)
    monkeypatch.setenv("PATH", "ORIGINAL")
    audio_transcriber._DLL_DIRS_REGISTERED = False

    audio_transcriber._register_nvidia_dll_dirs()
    assert sorted(Path(p).parent.name for p in registered) == ["cublas", "cudnn"]
    # ctranslate2 走传统 LoadLibrary 搜索(本机实测只认 PATH),必须同时前置 PATH
    import os as _os

    path_parts = _os.environ["PATH"].split(_os.pathsep)
    assert any("cublas" in p for p in path_parts[:2])
    assert path_parts[-1] == "ORIGINAL"

    registered.clear()
    audio_transcriber._register_nvidia_dll_dirs()  # 幂等:第二次不重复注册
    assert registered == []


def test_cuda_inference_failure_falls_back_to_cpu(tmp_path, monkeypatch):
    """S1 验收实测坑:CUDA 建模成功但推理时 cublas DLL 缺失才报错
    (ctranslate2 惰性 generator)。推理期 CUDA 错误必须同样回退 cpu+int8。"""
    import types

    module = types.ModuleType("faster_whisper")
    created: list = []

    class WhisperModel:
        def __init__(self, model_name, device="cpu", compute_type="default"):
            self.device = device
            created.append((model_name, device, compute_type))

        def transcribe(self, path, beam_size=None, temperature=None):
            if self.device == "cuda":
                # 模拟惰性生成器:迭代时才抛 cublas 缺失
                def _boom():
                    raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
                    yield  # pragma: no cover
                return _boom(), _FakeInfo()
            return iter([_FakeSeg(0.0, 1.0, "cpu ok")]), _FakeInfo()

    module.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    from mase.multimodal import audio_transcriber
    audio_transcriber._MODEL_CACHE.clear()
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")

    segments, info = audio_transcriber.transcribe(
        AudioTrack(wav, "audio/wav"), model_name="large-v3", device="cuda", compute_type="float16",
    )
    assert [s.text for s in segments] == ["cpu ok"]
    assert info["device_fallback"] is True
    assert info["device"] == "cpu" and info["compute_type"] == "int8"
    assert created[-1] == ("large-v3", "cpu", "int8")

    # 缓存已被 CPU 实例顶替:同设置再来一次不再动 CUDA
    audio_transcriber.transcribe(
        AudioTrack(wav, "audio/wav"), model_name="large-v3", device="cuda", compute_type="float16",
    )
    assert created.count(("large-v3", "cuda", "float16")) == 1


def test_missing_faster_whisper_actionable_error(tmp_path, monkeypatch):
    import builtins

    from mase.multimodal import audio_transcriber
    from mase.multimodal.document_loader import MissingDependencyError
    audio_transcriber._MODEL_CACHE.clear()
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)
    real_import = builtins.__import__

    def _no_fw(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("No module named 'faster_whisper'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_fw)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    with pytest.raises(MissingDependencyError, match=r"mase-memory\[audio\]"):
        audio_transcriber.transcribe(
            AudioTrack(wav, "audio/wav"), model_name="large-v3", device="cpu", compute_type="int8",
        )
