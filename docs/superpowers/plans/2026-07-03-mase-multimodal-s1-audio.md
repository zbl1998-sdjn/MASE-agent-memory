# MASE S1 语音转写与时间线事实 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 录音文件(wav/mp3/m4a)→ faster-whisper 本地转写(带 `[HH:MM:SS]` 时间戳审计底稿)→ 现有 Ollama 文本模型抽取带时间线 evidence 的事实 → 复用 S0 溯源管线入库。

**Architecture:** 两段式白盒:①`audio_transcriber.py`(faster-whisper 懒导入,确定性转写)②`audio_extractor.py`(实现 MediaExtractor,转写稿→`speech_facts` agent 严格 JSON 抽取)。前置一次接缝演化:`MediaExtractor.extract(asset, pages)` → `extract(asset, payload: MediaPayload)`,S0 特征测试断言不改。

**Tech Stack:** faster-whisper>=1.0(可选 extra `[audio]`,PyAV 自带 ffmpeg)、现有 Ollama qwen2.5:7b(事实抽取)、Windows SAPI TTS(验收样本合成)。

**Spec:** `docs/superpowers/specs/2026-07-03-mase-multimodal-s1-audio-design.md`(已批准)。

## Global Constraints

- Conventional Commits;一特性一提交;禁 `--no-verify`;提交尾行 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- ⚠️ 本仓库多行提交消息:用 Write 工具写消息文件到 scratchpad → `git commit -F <路径>`(heredoc 非首命令会静默失败,见项目记忆)。
- 红→绿→提交;测试通过公共接口;单元测试不碰真 ASR/真 LLM。
- 测试隔离:`monkeypatch.setenv("MASE_DB_PATH", str(tmp_path/"t.db"))` + `monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)`。
- 常量(spec 定死):`BEAM_SIZE = 5`、`TRANSCRIPT_CHUNK_CHARS = 6000`、`AUDIO_MAX_BYTES = 500 * 1024 * 1024`、默认 whisper 模型 `large-v3`、切换档 `large-v3-turbo`。
- 版本钉:`faster-whisper>=1.0,<2.0`。
- 全量测试命令:`python -m pytest -q -m "not integration and not slow"`(当前基线 674 passed)。

---

### Task 1: 接缝演化 — MediaPayload(断言不改的定向重构)

**Files:**
- Modify: `src/mase/multimodal/document_loader.py`(加 AudioTrack/MediaPayload/load_media)
- Modify: `src/mase/multimodal/extractor.py`(协议签名 + 共享 JSON 解析助手)
- Modify: `src/mase/multimodal/vision_extractor.py`(改读 payload.pages;解析逻辑改用共享助手)
- Modify: `src/mase/multimodal/ingest.py`(load_pages → load_media,extract 传 payload)
- Modify: `tests/test_vision_extractor.py`、`tests/test_multimodal_ingest.py`(只改调用形状,断言不动)
- Test: `tests/test_media_payload.py`(新,payload 形状特征测试)

**Interfaces:**
- Produces(后续任务依赖):
  - `document_loader.AudioTrack(path: Path, media_type: str, duration_seconds: float | None = None)`(frozen dataclass)
  - `document_loader.MediaPayload(pages: tuple[PageImage, ...] = (), audio: AudioTrack | None = None)`(frozen dataclass)
  - `document_loader.load_media(path: Path, media_type: str, *, pdf_dpi: int = 150) -> MediaPayload`(图像/PDF → pages;`audio/*` → audio=AudioTrack,不预解码)
  - `MediaExtractor.extract(self, asset: MediaAssetInfo, payload: MediaPayload) -> ExtractionResult`
  - `extractor.parse_json_blob(raw: str) -> dict | None`、`extractor.coerce_confidence(value) -> float`(共享解析助手)
  - `ExtractionResult` 新增可选字段 `metadata: dict[str, Any] | None = None`(进 to_json;S0 默认 None 不受影响)

- [ ] **Step 1: 写新特征测试(红)**

```python
# tests/test_media_payload.py
"""MediaPayload 接缝形状:图像/PDF 走 pages,音频走 AudioTrack 不预解码。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_load_media_image_fills_pages(tmp_path):
    from mase.multimodal.document_loader import load_media

    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNGdata")
    payload = load_media(img, "image/png")
    assert len(payload.pages) == 1
    assert payload.pages[0].image_bytes == b"\x89PNGdata"
    assert payload.audio is None


def test_load_media_audio_fills_audiotrack_without_decoding(tmp_path):
    from mase.multimodal.document_loader import load_media

    wav = tmp_path / "meeting.wav"
    wav.write_bytes(b"RIFFfake")  # 不解码:损坏字节也能封装
    payload = load_media(wav, "audio/wav")
    assert payload.pages == ()
    assert payload.audio is not None
    assert payload.audio.path == wav
    assert payload.audio.media_type == "audio/wav"
    assert payload.audio.duration_seconds is None


def test_extraction_result_metadata_serializes():
    from mase.multimodal.extractor import ExtractionResult
    import json

    result = ExtractionResult(
        full_text="t", candidate_facts=(), extractor_name="x",
        model_name="m", extractor_version="1", warnings=(),
        metadata={"asr": {"language": "zh"}},
    )
    assert json.loads(result.to_json())["metadata"]["asr"]["language"] == "zh"
```

- [ ] **Step 2: 确认红**

Run: `python -m pytest tests/test_media_payload.py -q`
Expected: FAIL — `cannot import name 'load_media'`

- [ ] **Step 3: 实现 document_loader 增量**

在 `document_loader.py` 的 `PageImage` 之后追加:

```python
@dataclass(frozen=True)
class AudioTrack:
    """音频轨引用:不预解码,faster-whisper 按路径自行解码(PyAV)。"""

    path: Path
    media_type: str
    duration_seconds: float | None = None


@dataclass(frozen=True)
class MediaPayload:
    """统一媒体载荷:视觉走 pages,音频走 audio;二选一填充。"""

    pages: tuple[PageImage, ...] = ()
    audio: AudioTrack | None = None


def load_media(path: Path, media_type: str, *, pdf_dpi: int = 150) -> MediaPayload:
    """把已过安全检查的文件封装为 MediaPayload。

    音频刻意不在此解码:转写器(faster-whisper/PyAV)直接吃文件路径,
    避免双重解码;时长等元数据由转写阶段回填到 result 元数据。
    """
    if media_type.startswith("audio/"):
        return MediaPayload(audio=AudioTrack(path=Path(path), media_type=media_type))
    return MediaPayload(pages=tuple(load_pages(path, media_type, pdf_dpi=pdf_dpi)))
```

- [ ] **Step 4: 演化 extractor.py**

4a. `ExtractionResult` 加字段(`warnings` 之后):

```python
    metadata: dict[str, Any] | None = None
```

(顶部 `from typing import Protocol` 改为 `from typing import Any, Protocol`。)

4b. 协议签名改为:

```python
    def extract(self, asset: MediaAssetInfo, payload: MediaPayload) -> ExtractionResult: ...
```

(import 行改 `from .document_loader import MediaPayload, PageImage`;PageImage 若不再被本文件引用则删掉。)

4c. 文件尾部加共享解析助手(从 vision_extractor 上提,便于 audio 复用):

```python
_JSON_BLOB_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_blob(raw: str) -> dict[str, Any] | None:
    """从模型回复中提取首个 JSON 对象;失败返回 None(调用方决定降级)。"""
    match = _JSON_BLOB_RE.search(raw)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def coerce_confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
```

(顶部补 `import re`;`pyproject.toml` per-file-ignores 加 `"src/mase/multimodal/extractor.py" = ["BLE001"]`,解析容错需要。)

- [ ] **Step 5: vision_extractor 改读 payload + 用共享助手**

`extract` 签名改 `def extract(self, asset: MediaAssetInfo, payload: MediaPayload) -> ExtractionResult:`,函数体首行加 `pages = payload.pages`;import 改 `from .document_loader import MediaPayload`、`from .extractor import CandidateFact, ExtractionResult, MediaAssetInfo, coerce_confidence, parse_json_blob`;`_parse_page_reply` 内联改用 `parse_json_blob(raw)`(None → 降级分支)与 `coerce_confidence`,删除本文件的 `_JSON_BLOB_RE` 与 `_coerce_confidence`。行为与断言不变。

- [ ] **Step 6: ingest 改用 load_media**

`ingest.py`:import 改 `from .document_loader import load_media`;主循环里

```python
            pages = load_pages(checked, media_type)
```
改为
```python
            payload = load_media(checked, media_type)
            page_count = len(payload.pages)
```
`mase2_register_media_asset(..., page_count=page_count)`、`MediaAssetInfo(..., page_count=page_count)`、`result = extractor.extract(asset_info, payload)`。

- [ ] **Step 7: 既有测试只改调用形状(断言不动)**

- `tests/test_vision_extractor.py`:`extractor.extract(_asset(), [PageImage(...)])` → `extractor.extract(_asset(), MediaPayload(pages=(PageImage(...),)))`(共 5 处;import 加 `from mase.multimodal.document_loader import MediaPayload`)。
- `tests/test_multimodal_ingest.py`:`FakeExtractor.extract(self, asset, pages)` → `extract(self, asset, payload)`(参数名改,体内未用 pages,无断言变化)。

- [ ] **Step 8: 全绿确认**

Run: `python -m pytest tests/test_media_payload.py tests/test_vision_extractor.py tests/test_multimodal_ingest.py -q`
Expected: 3+6+4 = 13 passed
Run: `python -m pytest -q -m "not integration and not slow"` → Expected: 677 passed(674+3)
Run: `python -m ruff check . && python -m mypy` → Expected: 干净

- [ ] **Step 9: 提交**

用 Write 写消息文件后 `git commit -F`:

```
refactor(multimodal): evolve extractor seam to MediaPayload

MediaExtractor.extract now takes MediaPayload (pages for visual media,
AudioTrack for audio, no pre-decoding). Vision behavior unchanged and
S0 characterization assertions untouched; shared JSON parse helpers
lifted into extractor.py for reuse by the audio extractor.
ExtractionResult gains optional metadata (serialized into result_json).
```

```bash
git add src/mase/multimodal/ tests/test_media_payload.py tests/test_vision_extractor.py tests/test_multimodal_ingest.py pyproject.toml
git commit -F <消息文件>
```

---

### Task 2: 安全边界音频扩展

**Files:**
- Modify: `src/mase/multimodal/security.py`
- Modify: `src/mase/multimodal/ingest.py`(max_bytes 默认改 None + 音频后缀映射)
- Modify: `src/mase/multimodal/cli.py`(--max-mb 默认 None)
- Test: `tests/test_multimodal_security.py`(追加)

**Interfaces:**
- Produces:
  - `ALLOWED_MEDIA_TYPES` 增 `.wav → audio/wav`、`.mp3 → audio/mpeg`、`.m4a → audio/mp4`
  - `AUDIO_MAX_BYTES = 500 * 1024 * 1024`
  - `default_max_bytes(media_type: str) -> int`(audio/* → AUDIO_MAX_BYTES,其余 DEFAULT_MAX_BYTES)
  - `classify_media(path, *, max_bytes: int | None = None) -> str`(None → 按类型默认;显式值 → 全类型统一,旧行为)
  - `ingest_folder(..., max_bytes: int | None = None)`;CLI `--max-mb` 默认 None

- [ ] **Step 1: 追加失败测试**

在 `tests/test_multimodal_security.py` 尾部追加:

```python
def test_audio_types_in_allowlist(tmp_path):
    from mase.multimodal.security import classify_media

    for name, expected in (("m.wav", "audio/wav"), ("m.MP3", "audio/mpeg"), ("m.m4a", "audio/mp4")):
        f = tmp_path / name
        f.write_bytes(b"x" * 10)
        assert classify_media(f) == expected


def test_per_type_default_max_bytes(tmp_path):
    """None → 音频 500MB / 图像 50MB 分档;显式 max_bytes 仍全类型统一。"""
    from mase.multimodal.security import AUDIO_MAX_BYTES, DEFAULT_MAX_BYTES, default_max_bytes

    assert default_max_bytes("audio/mpeg") == AUDIO_MAX_BYTES == 500 * 1024 * 1024
    assert default_max_bytes("image/png") == DEFAULT_MAX_BYTES


def test_audio_over_image_cap_but_under_audio_cap_passes(tmp_path, monkeypatch):
    from mase.multimodal import security
    from mase.multimodal.security import classify_media

    big_audio = tmp_path / "long.mp3"
    big_audio.write_bytes(b"x" * 128)
    # 通过打小上限常量模拟"超图像档但在音频档内",避免真写 60MB 文件
    monkeypatch.setattr(security, "DEFAULT_MAX_BYTES", 64)
    monkeypatch.setattr(security, "AUDIO_MAX_BYTES", 256)
    assert classify_media(big_audio) == "audio/mpeg"  # None → 按类型默认,128 < 256
```

- [ ] **Step 2: 确认红**

Run: `python -m pytest tests/test_multimodal_security.py -q`
Expected: 新增 3 项 FAIL(`AUDIO_MAX_BYTES` 不存在等)

- [ ] **Step 3: 实现**

`security.py`:

```python
ALLOWED_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}

DEFAULT_MAX_BYTES = 50 * 1024 * 1024   # 图像/文档单文件上限
AUDIO_MAX_BYTES = 500 * 1024 * 1024    # 音频单文件上限:1 小时会议 mp3 常超 50MB


def default_max_bytes(media_type: str) -> int:
    """按媒体类型给默认大小上限。"""
    return AUDIO_MAX_BYTES if media_type.startswith("audio/") else DEFAULT_MAX_BYTES
```

`classify_media` 签名改 `def classify_media(path: Path, *, max_bytes: int | None = None) -> str:`,大小检查改:

```python
    effective_max = max_bytes if max_bytes is not None else default_max_bytes(media_type)
    size = Path(path).stat().st_size
    if size > effective_max:
        raise UnsupportedMedia(f"文件超过大小上限 {effective_max}B: {path} ({size}B)")
```

(注意 monkeypatch 常量的测试要求 `default_max_bytes` 读**模块属性**而非闭包值——上面的直接引用即满足。)

`ingest.py`:签名 `max_bytes: int = DEFAULT_MAX_BYTES` → `max_bytes: int | None = None`(import 里 DEFAULT_MAX_BYTES 可删);`_SUFFIX_BY_MEDIA_TYPE` 增 `"audio/wav": "wav", "audio/mpeg": "mp3", "audio/mp4": "m4a"`。

`cli.py`:`--max-mb` 改 `type=int, default=None, help="单文件大小上限 MB(默认按类型:图像/文档 50,音频 500)"`;传参改 `max_bytes=args.max_mb * 1024 * 1024 if args.max_mb is not None else None`。

- [ ] **Step 4: 全绿 + 提交**

Run: `python -m pytest tests/test_multimodal_security.py tests/test_multimodal_cli.py tests/test_multimodal_ingest.py -q` → Expected: 全 passed
提交(单行可用 -m):

```bash
git add src/mase/multimodal/security.py src/mase/multimodal/ingest.py src/mase/multimodal/cli.py tests/test_multimodal_security.py
git commit -m "feat(multimodal): audio media types with per-type size caps"
```

---

### Task 3: 转写器 audio_transcriber.py

**Files:**
- Create: `src/mase/multimodal/audio_transcriber.py`
- Modify: `pyproject.toml`(extra `[audio]`;dev 加 faster-whisper;per-file-ignores 加 audio_transcriber/audio_extractor)
- Test: `tests/test_audio_transcriber.py`

**Interfaces:**
- Consumes: `document_loader.AudioTrack`
- Produces:
  - `TranscriptSegment(start_seconds: float, end_seconds: float, text: str)`(frozen)
  - `BEAM_SIZE = 5`;`DEFAULT_WHISPER_MODEL = "large-v3"`
  - `resolve_whisper_settings(model_override: str | None = None) -> dict`(keys: model_name/device/compute_type;env `MASE_WHISPER_MODEL/MASE_WHISPER_DEVICE/MASE_WHISPER_COMPUTE`,override > env > 默认 large-v3/cuda/float16)
  - `format_transcript(segments: list[TranscriptSegment]) -> str`(每段 `[HH:MM:SS] text` 一行)
  - `transcribe(track: AudioTrack, *, model_name: str, device: str, compute_type: str) -> tuple[list[TranscriptSegment], dict]`(info 含 language/duration_seconds/model_name/device/compute_type/device_fallback;cuda 建模失败自动回退 cpu+int8 并置 device_fallback=True;缺 faster_whisper 抛 `document_loader.MissingDependencyError` 且消息含 `mase-memory[audio]`;模型实例按 (model_name, device, compute) 进程内缓存)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_audio_transcriber.py
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
```

- [ ] **Step 2: 确认红**

Run: `python -m pytest tests/test_audio_transcriber.py -q`
Expected: FAIL — `No module named 'mase.multimodal.audio_transcriber'`

- [ ] **Step 3: 实现**

```python
# src/mase/multimodal/audio_transcriber.py
"""faster-whisper 本地转写(S1 第一段:确定性审计底稿)。

faster-whisper 懒导入(可选 extra [audio]);PyAV 自带 ffmpeg 库,无系统
级依赖。temperature=0、BEAM_SIZE=5 固定 → 同模型同音频输出确定。
CUDA 建模失败时回退 cpu+int8 并在 info 中如实标注,不静默也不崩批。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .document_loader import AudioTrack, MissingDependencyError

BEAM_SIZE = 5
DEFAULT_WHISPER_MODEL = "large-v3"

_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


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
    """建模并缓存;cuda 失败回退 cpu+int8。返回 (model, 实际device, 实际compute, 是否回退)。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise MissingDependencyError(
            "语音转写需要 faster-whisper。请安装: pip install \"mase-memory[audio]\" "
            "或 pip install \"faster-whisper>=1.0,<2.0\""
        ) from exc

    key = (model_name, device, compute_type)
    if key in _MODEL_CACHE:
        return (*_MODEL_CACHE[key],)
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        entry = (model, device, compute_type, False)
    except Exception:
        if device == "cuda":
            # CUDA DLL/驱动缺失是 Windows 常见坑;回退 CPU int8 保证批次能跑,
            # info.device_fallback 让验收证据如实反映降级。
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            entry = (model, "cpu", "int8", True)
        else:
            raise
    _MODEL_CACHE[key] = entry
    return entry


def transcribe(
    track: AudioTrack,
    *,
    model_name: str,
    device: str,
    compute_type: str,
) -> tuple[list[TranscriptSegment], dict[str, Any]]:
    """转写单个音频文件;返回 (segments, info)。info 全量入 result 元数据供审计。"""
    model, actual_device, actual_compute, fell_back = _load_model(model_name, device, compute_type)
    raw_segments, raw_info = model.transcribe(str(track.path), beam_size=BEAM_SIZE, temperature=0.0)
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
```

- [ ] **Step 4: pyproject 三处**

```toml
audio = [
    "faster-whisper>=1.0,<2.0",
]
```
(`multimodal` extra 之后);`all` 与 `dev` 列表各加 `"faster-whisper>=1.0,<2.0",`;per-file-ignores 加:

```toml
"src/mase/multimodal/audio_transcriber.py" = ["BLE001"]  # cuda 建模失败回退 cpu 需宽泛捕获
"src/mase/multimodal/audio_extractor.py" = ["BLE001"]    # LLM 事实抽取解析容错
```

装依赖:`python -m pip install "faster-whisper>=1.0,<2.0"`

- [ ] **Step 5: 全绿 + 提交**

Run: `python -m pytest tests/test_audio_transcriber.py -q` → Expected: 6 passed
提交消息(Write→`git commit -F`):

```
feat(multimodal): faster-whisper audio transcriber

Deterministic transcription (temperature=0, beam_size=5) into
[HH:MM:SS]-prefixed audit transcripts. Lazy import behind the new
[audio] extra with an actionable install hint; per-settings model
cache for batch runs; CUDA failures fall back to cpu+int8 with an
honest device_fallback flag in the info dict.
```

```bash
git add src/mase/multimodal/audio_transcriber.py pyproject.toml tests/test_audio_transcriber.py
git commit -F <消息文件>
```

---

### Task 4: 音频抽取器 audio_extractor.py + speech_facts 配置

**Files:**
- Create: `src/mase/multimodal/audio_extractor.py`
- Modify: `config.json`(models 加 `speech_facts` agent,vision 之后)
- Test: `tests/test_audio_extractor.py`

**Interfaces:**
- Consumes: Task 3 `transcribe/format_transcript/resolve_whisper_settings/TranscriptSegment`;Task 1 `MediaPayload/parse_json_blob/coerce_confidence`;`ModelInterface.chat("speech_facts", ...)`
- Produces:
  - `AUDIO_EXTRACTOR_VERSION = "1"`;`TRANSCRIPT_CHUNK_CHARS = 6000`;`SPEECH_FACTS_SYSTEM`(提示词)
  - `class AudioExtractor: name="audio"; version="1"`
    - `__init__(self, model_interface=None, *, whisper_model: str | None = None, transcribe_fn=None)`(transcribe_fn 可注入假转写供测试;默认真 transcribe)
    - `supports(media_type)` → 仅 `audio/*`
    - `extract(asset, payload)` → 转写 → full_text=format_transcript → 分块(6000 字符,segment 边界)→ 逐块 chat("speech_facts") → 合并 facts;metadata={"asr": info};evidence 无 `[HH:MM:SS]` 的事实保留但记 warning;块数>1 记 `chunked: N parts`
  - config.json `models.speech_facts`:`{"provider": "ollama", "model_name": "qwen2.5:7b", "ollama_options": {"num_ctx": 8192}, "temperature": 0.0, "max_tokens": 1024}`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_audio_extractor.py
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
    replies = [json.dumps({"facts": []}), json.dumps({"facts": []})]
    fake_llm = FakeModelInterface(replies)
    extractor = AudioExtractor(fake_llm, transcribe_fn=_fake_transcribe(segs))
    # 压小分块阈值触发两块
    orig = audio_extractor.TRANSCRIPT_CHUNK_CHARS
    audio_extractor.TRANSCRIPT_CHUNK_CHARS = 300
    try:
        result = extractor.extract(_asset(), _payload(tmp_path))
    finally:
        audio_extractor.TRANSCRIPT_CHUNK_CHARS = orig
    assert len(fake_llm.calls) == 2
    assert any(w.startswith("chunked:") for w in result.warnings)
    # 每块都是完整行(segment 边界),不劈开单段
    for call in fake_llm.calls:
        for line in call["messages"][0]["content"].splitlines():
            assert line.startswith("[")


def test_malformed_llm_reply_degrades_to_transcript_only(tmp_path):
    from mase.multimodal.audio_extractor import AudioExtractor

    segs = [TranscriptSegment(0.0, 3.0, "内容")]
    extractor = AudioExtractor(FakeModelInterface(["not json"]), transcribe_fn=_fake_transcribe(segs))
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
```

- [ ] **Step 2: 确认红**

Run: `python -m pytest tests/test_audio_extractor.py -q`
Expected: FAIL — `No module named 'mase.multimodal.audio_extractor'`

- [ ] **Step 3: 实现**

```python
# src/mase/multimodal/audio_extractor.py
"""音频抽取器(S1 第二段:转写稿 → 文本 LLM 抽时间线事实)。

两段式白盒:转写稿(audit 底稿)由 audio_transcriber 生成并完整入
full_text;事实抽取用现有 Ollama 文本模型(config `speech_facts`),
严格 JSON 契约与 S0 视觉一致,另要求 evidence 引用带 [HH:MM:SS] 的
原文行 → 每条事实自带时间线锚点。畸形回复降级为"仅转写稿",绝不抛穿。
"""
from __future__ import annotations

from typing import Any

from .audio_transcriber import (
    TranscriptSegment,
    format_transcript,
    resolve_whisper_settings,
    transcribe,
)
from .document_loader import MediaPayload
from .extractor import (
    CandidateFact,
    ExtractionResult,
    MediaAssetInfo,
    coerce_confidence,
    parse_json_blob,
)

AUDIO_EXTRACTOR_VERSION = "1"
TRANSCRIPT_CHUNK_CHARS = 6000  # 超过则按 segment 边界分块抽取(spec §5)

SPEECH_FACTS_SYSTEM = """你是会议纪要事实抽取器。输入是带 [HH:MM:SS] 时间戳的会议/语音转写稿。
请输出严格的 JSON(不要 markdown 代码围栏),形状:
{"facts": [{"category": "<user_preferences|people_relations|project_status|finance_budget|location_events|general_facts 之一>",
            "key": "<snake_case 唯一键>", "value": "<事实当前值>",
            "confidence": <0到1的数字>,
            "evidence": "<引用转写稿中支撑该事实的原文行,必须带 [HH:MM:SS] 前缀>"}]}
规则:
- 只提取转写稿中明确说出的决策、待办、承诺、预算、时间安排等事实,不要推测;
- evidence 必须逐字引用转写稿的整行(含时间戳前缀);
- 没有可提取的事实就返回 {"facts": []}。"""


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

        facts: list[CandidateFact] = []
        warnings: list[str] = []
        llm_model = "unknown"
        chunks = _chunk_transcript(segments)
        if len(chunks) > 1:
            warnings.append(f"chunked: {len(chunks)} parts")

        for chunk_text in chunks:
            response = self.model_interface.chat(
                "speech_facts",
                messages=[{"role": "user", "content": chunk_text}],
                override_system_prompt=SPEECH_FACTS_SYSTEM,
            )
            llm_model = str(response.get("model") or llm_model)
            raw = str((response.get("message") or {}).get("content") or "")
            payload_json = parse_json_blob(raw)
            if payload_json is None:
                warnings.append("non_json_response")
                continue
            for item in payload_json.get("facts") or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                value = str(item.get("value") or "").strip()
                if not key or not value:
                    continue
                evidence = str(item.get("evidence") or "").strip()
                if not evidence.startswith("["):
                    warnings.append(f"fact {key}: evidence missing timestamp")
                facts.append(
                    CandidateFact(
                        category=str(item.get("category") or "general_facts"),
                        key=key,
                        value=value,
                        confidence=coerce_confidence(item.get("confidence")),
                        evidence=evidence,
                    )
                )

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


def _chunk_transcript(segments: list[TranscriptSegment]) -> list[str]:
    """按 segment 边界切块:不劈开单段,块字符数 ≤ TRANSCRIPT_CHUNK_CHARS(单段超限自成一块)。"""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for seg in segments:
        line = format_transcript([seg])
        if current and current_len + len(line) + 1 > TRANSCRIPT_CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]
```

- [ ] **Step 4: config.json 加 speech_facts agent**

用与 S0 相同的程序化插入(round-trip 已验证等价),在 `vision` 之后插:

```json
"speech_facts": {
  "provider": "ollama",
  "model_name": "qwen2.5:7b",
  "ollama_options": {"num_ctx": 8192},
  "temperature": 0.0,
  "max_tokens": 1024
}
```

- [ ] **Step 5: 全绿 + 提交**

Run: `python -m pytest tests/test_audio_extractor.py -q` → Expected: 6 passed
Run: `python -m ruff check src/mase/multimodal/` → Expected: 干净
提交消息(Write→`git commit -F`):

```
feat(multimodal): audio extractor with timeline facts via speech_facts agent

Two-stage whitebox: transcriber output is the audit transcript
(full_text verbatim); fact extraction runs the existing qwen2.5:7b
through a strict-JSON contract requiring [HH:MM:SS]-quoted evidence.
Segment-boundary chunking above 6000 chars, malformed replies degrade
to transcript-only, model_name records ASR+LLM attribution.
```

```bash
git add src/mase/multimodal/audio_extractor.py config.json tests/test_audio_extractor.py
git commit -F <消息文件>
```

---

### Task 5: ingest 调度器 + CLI --whisper-model

**Files:**
- Modify: `src/mase/multimodal/ingest.py`
- Modify: `src/mase/multimodal/cli.py`
- Test: `tests/test_multimodal_ingest.py`(追加)、`tests/test_multimodal_cli.py`(追加)

**Interfaces:**
- Produces:
  - `ingest_folder(..., whisper_model: str | None = None)`;`extractor=None` 时默认调度器 = `[VisionExtractor(mode=mode), AudioExtractor(whisper_model=whisper_model)]` 按 `supports(media_type)` 取第一个命中;无命中 → skipped reason `no_extractor`
  - CLI 新 flag `--whisper-model`(透传 whisper_model)

- [ ] **Step 1: 追加失败测试**

`tests/test_multimodal_ingest.py` 尾部追加:

```python
def test_mixed_folder_dispatches_by_media_type(tmp_path, monkeypatch):
    """图像走 vision、音频走 audio,一次批处理各归其位(全假抽取,不碰真模型)。"""
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "pic.png").write_bytes(b"img-bytes")
    (docs / "talk.wav").write_bytes(b"RIFF-bytes")

    from mase.multimodal import ingest as ingest_mod
    from mase.multimodal.ingest import ingest_folder

    class _StubVision:
        name, version = "vision", "1"
        def supports(self, media_type): return not media_type.startswith("audio/")
        def extract(self, asset, payload):
            return FakeExtractor().extract(asset, payload)

    class _StubAudio:
        name, version = "audio", "1"
        seen = []
        def supports(self, media_type): return media_type.startswith("audio/")
        def extract(self, asset, payload):
            _StubAudio.seen.append(asset.media_type)
            assert payload.audio is not None
            return FakeExtractor().extract(asset, payload)

    monkeypatch.setattr(ingest_mod, "_default_extractors", lambda mode, whisper_model: [_StubVision(), _StubAudio()])
    report = ingest_folder(docs, asset_root=assets)
    assert sorted(report.processed) == ["pic.png", "talk.wav"]
    assert _StubAudio.seen == ["audio/wav"]


def test_no_extractor_supports_type_is_skipped(tmp_path, monkeypatch):
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "talk.wav").write_bytes(b"RIFF")

    from mase.multimodal import ingest as ingest_mod
    from mase.multimodal.ingest import ingest_folder

    class _OnlyVision:
        name, version = "vision", "1"
        def supports(self, media_type): return media_type.startswith("image/")
        def extract(self, asset, payload): raise AssertionError("不应被调用")

    monkeypatch.setattr(ingest_mod, "_default_extractors", lambda mode, whisper_model: [_OnlyVision()])
    report = ingest_folder(docs, asset_root=assets)
    assert any(s["file"] == "talk.wav" and s["reason"] == "no_extractor" for s in report.skipped)
```

`tests/test_multimodal_cli.py` 尾部追加:

```python
def test_cli_passes_whisper_model(tmp_path, monkeypatch):
    from mase.multimodal import cli

    captured = {}
    monkeypatch.setattr(cli, "ingest_folder", lambda folder, **kw: (captured.update(kw), _fake_report())[1])
    docs = tmp_path / "docs"
    docs.mkdir()
    assert cli.main([str(docs), "--whisper-model", "large-v3-turbo"]) == 0
    assert captured["whisper_model"] == "large-v3-turbo"
```

- [ ] **Step 2: 确认红**

Run: `python -m pytest tests/test_multimodal_ingest.py tests/test_multimodal_cli.py -q`
Expected: 新增 3 项 FAIL(`_default_extractors` 不存在 / `whisper_model` 意外参数)

- [ ] **Step 3: 实现**

`ingest.py`:

```python
def _default_extractors(mode: str | None, whisper_model: str | None) -> list[MediaExtractor]:
    """默认抽取器组:视觉在前、音频在后;按 supports() 调度。懒导入避免无关依赖。"""
    from .audio_extractor import AudioExtractor
    from .vision_extractor import VisionExtractor

    return [VisionExtractor(mode=mode), AudioExtractor(whisper_model=whisper_model)]
```

`ingest_folder` 签名加 `whisper_model: str | None = None,`;默认抽取器逻辑改为:

```python
    extractors: list[MediaExtractor]
    if extractor is not None:
        extractors = [extractor]
    else:
        extractors = _default_extractors(mode, whisper_model)
```

主循环在 classify 之后、read_bytes 之前加调度:

```python
        selected = next((e for e in extractors if e.supports(media_type)), None)
        if selected is None:
            skipped.append({"file": rel_name, "reason": "no_extractor", "media_type": media_type})
            continue
```

后续 `find_extraction(..., extractor_name=extractor.name, ...)` 与 `result = extractor.extract(...)` 中的 `extractor` 全部改为 `selected`。

注意:显式 `extractor` 参数(测试用)也走 `extractors=[extractor]` + supports 调度——FakeExtractor.supports 返回 True,行为不变。

`cli.py`:加

```python
    parser.add_argument("--whisper-model", default=None, help="ASR 模型,如 large-v3-turbo(默认 large-v3,可用 MASE_WHISPER_MODEL 覆盖)")
```

`ingest_folder(...)` 调用加 `whisper_model=args.whisper_model,`。

- [ ] **Step 4: 全绿 + 提交**

Run: `python -m pytest tests/test_multimodal_ingest.py tests/test_multimodal_cli.py -q` → Expected: 6+4=10 passed
Run: `python -m pytest -q -m "not integration and not slow"` → Expected: 全绿

```bash
git add src/mase/multimodal/ingest.py src/mase/multimodal/cli.py tests/test_multimodal_ingest.py tests/test_multimodal_cli.py
git commit -m "feat(multimodal): media-type extractor dispatch and --whisper-model flag"
```

---

### Task 6: S1 验收 harness + 全量门禁 + 真跑验收

**Files:**
- Create: `scripts/run_s1_acceptance.py`
- Test: 无新增单元测试(harness 为 integration 工具);全量门禁 + 真跑证据收口

**Interfaces:**
- Produces: `scripts/run_s1_acceptance.py`,行为:
  1. Windows SAPI TTS(PowerShell `System.Speech`)离线合成 WAV 样本,内容 `"The phoenix project budget of four thousand two hundred euros was approved by acme corporation in the meeting."`;锚词 `("phoenix", "acme")`
  2. 双 lane:`large-v3`(默认)与 `large-v3-turbo`(`whisper_model` 覆盖),各自独立 `MASE_DB_PATH`/资产根
  3. 每 lane 断言:`extractions >= 1`、`infra_errors == 0`、转写稿(memory_log 里的 full_text)含全部锚词(不区分大小写)、锚词经 `mase2_search_memory` 可召回、≥1 条事实且其 evidence 含 `[HH:MM:SS]` 形状(regex `\[\d{2}:\d{2}:\d{2}\]`)、溯源链走到资产字节、`metadata.asr.device_fallback` 如实记录(若 True 在 evidence 标注 CPU 降级,不算 FAIL 但必须可见)
  4. evidence.json / evidence.md 落 `<runs>/s1_acceptance/<UTC时间戳>/`;PASS→0,FAIL→1,依赖缺失→2

- [ ] **Step 1: 实现 harness**

结构复用 `scripts/run_s0_acceptance.py`(同仓可参照),差异点:

```python
# scripts/run_s1_acceptance.py 关键段(其余骨架同 run_s0_acceptance.py)
import re
import subprocess

ANCHORS = ("phoenix", "acme")
SAMPLE_SENTENCE = (
    "The phoenix project budget of four thousand two hundred euros "
    "was approved by acme corporation in the meeting."
)
TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}\]")


def make_sample(sample_dir: Path) -> Path:
    """Windows SAPI 离线合成真语音 WAV;无网络依赖。"""
    sample_dir.mkdir(parents=True, exist_ok=True)
    wav = sample_dir / "meeting.wav"
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{wav}'); "
        f"$s.Speak('{SAMPLE_SENTENCE}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=120)
    if not wav.exists() or wav.stat().st_size < 1000:
        raise RuntimeError(f"SAPI TTS 合成失败: {wav}")
    return wav


def run_lane(lane: str, whisper_model: str | None, samples: Path, out_dir: Path) -> dict:
    db_path = out_dir / f"lane_{lane}.db"
    asset_dir = out_dir / f"assets_{lane}"
    os.environ["MASE_DB_PATH"] = str(db_path)
    os.environ["MASE_MEDIA_ASSETS_DIR"] = str(asset_dir)
    from mase.multimodal.ingest import ingest_folder
    from mase_tools.memory.api import mase2_search_memory

    started = time.perf_counter()
    report = ingest_folder(samples, whisper_model=whisper_model, asset_root=asset_dir)
    elapsed = time.perf_counter() - started

    failures: list[str] = []
    if report.extractions < 1:
        failures.append(f"extractions={report.extractions} < 1")
    if report.infra_errors:
        failures.append(f"infra_errors={list(report.infra_errors)}")

    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    log_row = conn.execute("SELECT content FROM memory_log WHERE source_media_id IS NOT NULL LIMIT 1").fetchone()
    transcript = str(log_row["content"]) if log_row else ""
    facts = conn.execute(
        "SELECT entity_key FROM entity_state WHERE source_media_id IS NOT NULL"
    ).fetchall()
    ext_row = conn.execute("SELECT result_json FROM media_extraction LIMIT 1").fetchone()
    conn.close()

    for anchor in ANCHORS:
        if anchor not in transcript.lower():
            failures.append(f"anchor {anchor!r} not in transcript")
        hits = mase2_search_memory([anchor], limit=5)
        if not any(anchor in str(h.get("content", "")).lower() for h in hits):
            failures.append(f"anchor {anchor!r} not recalled")

    result_json = json.loads(ext_row["result_json"]) if ext_row else {}
    timestamped_facts = [
        f for f in result_json.get("candidate_facts", []) if TIMESTAMP_RE.search(str(f.get("evidence", "")))
    ]
    if not timestamped_facts:
        failures.append("no fact with [HH:MM:SS] evidence")
    asr_info = (result_json.get("metadata") or {}).get("asr") or {}
    # device_fallback=True 不判 FAIL,但必须出现在 evidence 里(诚实降级标注)
    # 溯源链抽样:同 run_s0_acceptance._check_provenance_chain(复制该函数)

    return {"lane": lane, "whisper_model": whisper_model or "large-v3", "elapsed_seconds": round(elapsed, 2),
            "report": {"processed": list(report.processed), "extractions": report.extractions,
                       "facts_written": report.facts_written, "infra_errors": list(report.infra_errors),
                       "warnings_sample": list(result_json.get("warnings", []))[:5]},
            "transcript_excerpt": transcript[:300], "facts": [r["entity_key"] for r in facts],
            "timestamped_fact_count": len(timestamped_facts), "asr": asr_info, "failures": failures}
```

main 骨架同 S0:检查 faster-whisper 可导入(否则 exit 2 + 安装指引)→ make_sample → 双 lane(`("largev3", None)` 与 `("turbo", "large-v3-turbo")`)→ evidence.json/md 写 `<runs>/s1_acceptance/<ts>/` → verdict。`_check_provenance_chain` 从 run_s0_acceptance.py 复制(9 行,两脚本独立可运行优先于 DRY)。

- [ ] **Step 2: 全量门禁**

```bash
python -m pytest -q -m "not integration and not slow"
python -m ruff check .
python -m mypy
python -m compileall -q -x "(legacy_archive|run_artifacts|dist|build|\.venv|venv|memory|benchmarks[\\/]external-benchmarks|__pycache__|\.pytest_cache)" .
python scripts/audit_repo_hygiene.py --strict
python scripts/audit_anti_overfit.py --strict
npm --prefix frontend run typecheck && npm --prefix frontend test && npm --prefix frontend run build
git diff --check
```
Expected: 全绿。

- [ ] **Step 3: 提交 harness**

```bash
git add scripts/run_s1_acceptance.py
git commit -m "feat(multimodal): S1 acceptance harness with SAPI-synthesized speech"
```

- [ ] **Step 4: 真模型验收(完成的唯一定义)**

```bash
python -X utf8 scripts/run_s1_acceptance.py --runs-dir E:/MASE-runs
```
首跑自动从 HF 下载 whisper 权重(large-v3 ~3GB、turbo ~1.6GB)。Expected: `verdict=PASS`,evidence 落盘。CUDA DLL 缺失时 lane 会以 cpu+int8 降级跑通——evidence 必须如实标注 `device_fallback`,此时可补 `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` 后重跑升级为 GPU 证据。**未 PASS 前 S1 只标"待验收"。**

- [ ] **Step 5: 收口**

CHANGELOG 记 `## [0.6.0] — S1 语音转写与时间线事实`(含 evidence 路径),单独 `docs(changelog):` 提交;spec 状态行更新为已验收,单独 `docs(spec):` 提交;tag 由用户决定。

---

## Self-Review(已执行)

1. **Spec 覆盖**:§3 架构增量 → T1(接缝/load_media)、T2(security)、T3(transcriber)、T4(extractor+config)、T5(调度+CLI)、T6(harness);§4 → T1;§5 两段契约/分块/时间戳 evidence → T3+T4;§6 安全增量 → T2+T3(降级);§7 测试与验收 → 各任务 Step 1 + T6;§8 风险 → T3 cuda 回退 + T6 Step 4 说明;§9 非目标未越界。无缺口。
2. **占位符**:T6 harness 标注"骨架同 run_s0_acceptance.py"并给出全部差异代码与复制指令(同仓文件可参照,非悬空);其余任务代码完整。
3. **类型一致性**:`MediaPayload(pages, audio)`/`AudioTrack(path, media_type, duration_seconds)` T1↔T3↔T4↔T5 一致;`transcribe(track, *, model_name, device, compute_type) -> (list[TranscriptSegment], dict)` T3↔T4 一致;`parse_json_blob/coerce_confidence` T1↔T4 一致;`_default_extractors(mode, whisper_model)` T5 测试与实现一致;`ExtractionResult.metadata` T1↔T4↔T6(result_json 读取)一致。
