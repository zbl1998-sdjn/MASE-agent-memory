"""faster-whisper 本地转写(S1 第一段:确定性审计底稿)。

faster-whisper 懒导入(可选 extra [audio]);PyAV 自带 ffmpeg 库,无系统
级依赖。temperature=0、BEAM_SIZE=5 固定 → 同模型同音频输出确定。
CUDA 建模失败时回退 cpu+int8 并在 info 中如实标注,不静默也不崩批。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .document_loader import AudioTrack, MissingDependencyError

BEAM_SIZE = 5
DEFAULT_WHISPER_MODEL = "large-v3"

_MODEL_CACHE: dict[tuple[str, str, str], tuple[Any, str, str, bool]] = {}
_DLL_DIRS_REGISTERED = False


def _register_nvidia_dll_dirs() -> None:
    """把 pip 安装的 nvidia wheels(cublas/cudnn)的 bin 目录加进 DLL 搜索路径。

    Windows 上 ctranslate2 用传统 LoadLibrary 搜索找 cublas64_12/cudnn 系列
    DLL(本机实测:仅 add_dll_directory 不生效,传统搜索只认 PATH),
    pip wheel 落在 site-packages/nvidia/<pkg>/bin 却不在默认搜索路径。
    因此两种机制都注册:add_dll_directory(带搜索标志的加载)+ 前置
    PATH(传统 LoadLibrary)。幂等 + best-effort,非 Windows 静默跳过。
    """
    global _DLL_DIRS_REGISTERED
    if _DLL_DIRS_REGISTERED:
        return
    _DLL_DIRS_REGISTERED = True
    try:
        import site

        found: list[str] = []
        for site_dir in site.getsitepackages():
            nvidia_root = Path(site_dir) / "nvidia"
            if not nvidia_root.is_dir():
                continue
            for bin_dir in sorted(nvidia_root.glob("*/bin")):
                if any(bin_dir.glob("*.dll")):
                    found.append(str(bin_dir))
                    os.add_dll_directory(str(bin_dir))
        if found:
            os.environ["PATH"] = os.pathsep.join([*found, os.environ.get("PATH", "")])
    except Exception:
        pass


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str


def resolve_whisper_settings(model_override: str | None = None) -> dict[str, str]:
    """whisper 引擎配置:显式覆盖 > env > 默认(large-v3/cuda/float16)。"""
    return {
        "model_name": model_override or os.environ.get("MASE_WHISPER_MODEL") or DEFAULT_WHISPER_MODEL,
        "device": os.environ.get("MASE_WHISPER_DEVICE") or "cuda",
        "compute_type": os.environ.get("MASE_WHISPER_COMPUTE") or "float16",
    }


def _format_hhmmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def format_transcript(segments: list[TranscriptSegment]) -> str:
    """审计底稿格式:每段一行 ``[HH:MM:SS] text``。"""
    return "\n".join(f"[{_format_hhmmss(seg.start_seconds)}] {seg.text}" for seg in segments)


def _load_model(model_name: str, device: str, compute_type: str) -> tuple[Any, str, str, bool]:
    """建模并缓存;环境性建模失败回退 cpu+int8。返回 (model, 实际device, 实际compute, 是否回退)。"""
    _register_nvidia_dll_dirs()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise MissingDependencyError(
            "语音转写需要 faster-whisper。请安装: pip install \"mase-memory[audio]\" "
            "或 pip install \"faster-whisper>=1.0,<2.0\""
        ) from exc

    key = (model_name, device, compute_type)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        entry = (model, device, compute_type, False)
    except Exception:
        if (device, compute_type) == ("cpu", "int8"):
            raise
        # 环境性建模失败——CUDA DLL/驱动缺失(Windows 常见坑),或 CPU 不支持
        # float16 权重计算(dev 实录 2026-07-06 音频 lane 全 infra)——统一回退
        # cpu+int8 保证批次能跑,info.device_fallback 让验收证据如实反映降级。
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        entry = (model, "cpu", "int8", True)
    _MODEL_CACHE[key] = entry
    return entry


_CUDA_ERROR_MARKERS = ("cublas", "cudnn", "cuda", "cudart")


def _is_cuda_runtime_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _CUDA_ERROR_MARKERS)


def transcribe(
    track: AudioTrack,
    *,
    model_name: str,
    device: str,
    compute_type: str,
) -> tuple[list[TranscriptSegment], dict[str, Any]]:
    """转写单个音频文件;返回 (segments, info)。info 全量入 result 元数据供审计。

    CUDA 失败有两个时点:建模期(_load_model 已回退)与推理期——
    ctranslate2 的 transcribe 是惰性 generator,cublas/cudnn DLL 缺失
    要到迭代 segments 时才爆(S1 验收实测)。两处都回退 cpu+int8,
    并把 CPU 实例顶进缓存,后续文件不再重试 CUDA。
    """
    model, actual_device, actual_compute, fell_back = _load_model(model_name, device, compute_type)
    try:
        raw_segments, raw_info = model.transcribe(str(track.path), beam_size=BEAM_SIZE, temperature=0.0)
        segments = [
            TranscriptSegment(float(seg.start), float(seg.end), str(seg.text).strip())
            for seg in raw_segments
        ]
    except Exception as error:
        if actual_device != "cuda" or not _is_cuda_runtime_error(error):
            raise
        cpu_model, actual_device, actual_compute, _ = _load_model(model_name, "cpu", "int8")
        # 顶替失效的 CUDA 缓存项,批处理内后续文件直接走 CPU
        _MODEL_CACHE[(model_name, device, compute_type)] = (cpu_model, "cpu", "int8", True)
        fell_back = True
        raw_segments, raw_info = cpu_model.transcribe(str(track.path), beam_size=BEAM_SIZE, temperature=0.0)
        segments = [
            TranscriptSegment(float(seg.start), float(seg.end), str(seg.text).strip())
            for seg in raw_segments
        ]
    info: dict[str, Any] = {
        "language": getattr(raw_info, "language", None),
        "duration_seconds": getattr(raw_info, "duration", None),
        "model_name": model_name,
        "device": actual_device,
        "compute_type": actual_compute,
        "device_fallback": fell_back,
        "beam_size": BEAM_SIZE,
    }
    return segments, info
