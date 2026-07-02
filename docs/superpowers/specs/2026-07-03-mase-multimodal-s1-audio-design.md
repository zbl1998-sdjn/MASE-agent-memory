# MASE 多模态能力 — S1 设计:语音转写与时间线事实

- 状态:草案(待用户审阅)
- 日期:2026-07-03
- 前置:S0 已验收(v0.5.0,`docs/superpowers/specs/2026-07-02-mase-multimodal-s0-design.md`)。本文件只写 S1 增量,S0 既定模式(资产库溯源、批处理 CLI、逐文件隔离、幂等键、双 lane 验收证据)直接沿用不重复。

---

## 1. 目标

录音文件(会议/语音备忘,wav/mp3/m4a)→ 本地 ASR 转写(带时间戳,审计底稿)→ 现有文本 LLM 抽取决策/待办/承诺(evidence 引用带时间戳原文)→ 带完整溯源写入白盒记忆。

**白盒增强点**:两段式比 S0 单段更可审——转写稿与事实抽取各自独立可检视、可重跑、可纠正。

## 2. 已定决策

| 决策点 | 选定 | 依据 |
|---|---|---|
| ASR 引擎 | **faster-whisper**(可选 extra `[audio]`) | pip 即装,PyAV 自带 ffmpeg 库(无系统依赖,同 PyMuPDF 模式),CUDA 加速,社区主流。Ollama 已核实**不支持音频输入**,排除 |
| 模型档位 | **默认 `large-v3`,可切 `large-v3-turbo`** | large-v3 中文/多语质量最好(企业中文会议刚需);turbo 英语快 8 倍。双档按配置切,与 S0 双视觉模型同模式 |
| 事实抽取 | **两段式:转写稿 → 文本 LLM 抽事实** | 转写稿=确定性审计底稿;事实抽取用现有 qwen2.5:7b(config 新增 `speech_facts` agent),严格 JSON 契约同 S0 |
| 格式范围 | **wav / mp3 / m4a** | 覆盖录音笔/手机/会议软件导出;PyAV 原生解码 |

## 3. 架构增量

```
src/mase/multimodal/
  audio_transcriber.py   ① ASR:faster-whisper 懒导入 → TranscriptSegment 列表 → 带 [HH:MM:SS] 前缀的转写稿
  audio_extractor.py     ② MediaExtractor 实现:转写 → model_interface.chat("speech_facts") 抽事实 → ExtractionResult
  document_loader.py     扩:load_media(path, media_type) -> MediaPayload;音频不解码,只封 AudioTrack(path/duration)
  extractor.py           接缝演化(见 §4)
  security.py            allowlist 加 .wav/.mp3/.m4a;音频独立大小上限 AUDIO_MAX_BYTES = 500MB
  ingest.py              默认抽取器改为调度器:按 supports(media_type) 在 [vision, audio] 中选;单抽取器 param 保留供测试
  cli.py                 加 --whisper-model 透传

config.json              models 新增 "speech_facts" agent(provider=ollama, qwen2.5:7b, temp 0;系统提示与解析器同居 audio_extractor.py)
pyproject.toml           optional extra [audio] = ["faster-whisper>=1.0,<2.0"];dev 同步加
scripts/run_s1_acceptance.py  双 lane 验收 harness(§7)
```

whisper 引擎配置不进 `config.json` models(它不是 chat provider):env `MASE_WHISPER_MODEL`(默认 large-v3)/ `MASE_WHISPER_DEVICE`(默认 cuda,失败回退 cpu)/ `MASE_WHISPER_COMPUTE`(默认 float16,cpu 时 int8),CLI `--whisper-model` 优先于 env。

## 4. 接缝演化(定向重构,一次到位)

S0 的 `MediaExtractor.extract(asset, pages: list[PageImage])` 是图像形状的,音频塞不进去。演化为:

```python
@dataclass(frozen=True)
class AudioTrack:
    path: Path                    # 已过 jail 的本地文件;PyAV/faster-whisper 直接按路径解码
    media_type: str
    duration_seconds: float | None  # 可得时填,资产元数据用

@dataclass(frozen=True)
class MediaPayload:
    pages: tuple[PageImage, ...] = ()
    audio: AudioTrack | None = None

class MediaExtractor(Protocol):
    name: str
    version: str
    def supports(self, media_type: str) -> bool: ...
    def extract(self, asset: MediaAssetInfo, payload: MediaPayload) -> ExtractionResult: ...
```

- `VisionExtractor` 改读 `payload.pages`,行为零变化,version 仍为 "1"。
- S0 既有特征测试**断言不改,只改调用形状**(构造 MediaPayload)。
- `document_loader.load_pages` 保留为内部函数,新公开入口 `load_media(path, media_type) -> MediaPayload`(图像/PDF → pages;音频 → AudioTrack,不预解码)。

## 5. 两段式抽取契约

**① 转写(audio_transcriber.py)**

```python
@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str

def transcribe(track: AudioTrack, *, model_name: str, device: str, compute_type: str) -> tuple[list[TranscriptSegment], dict]
# 返回 (segments, info):info 含 language/duration/model_name,写进 result_json 供审计
```

转写稿格式(= ExtractionResult.full_text,审计底稿):每段一行 `[HH:MM:SS] text`。temperature=0、beam_size=5(faster-whisper 默认,写死为常量)→ 同模型同音频输出确定。

**② 事实抽取(audio_extractor.py)**

- `model_interface.chat("speech_facts", ...)`,严格 JSON 契约与 S0 视觉一致(category 对齐 PROFILE_TEMPLATES / key / value / confidence / evidence),另加规则:**evidence 必须引用转写稿中带 `[HH:MM:SS]` 前缀的原文行** → 每条事实自带时间线锚点。
- 长转写分块:转写稿超过 `TRANSCRIPT_CHUNK_CHARS = 6000` 时按 segment 边界切块(不劈开单段),逐块抽取后合并;块数记入 warnings(如 `chunked: 3 parts`)。
- 畸形 JSON 降级同 S0:该块无事实 + warning,转写稿仍完整入库。
- `AudioExtractor.name = "audio"`,`version = "1"`;`supports()` 仅 `audio/*`。幂等键沿用 (sha256, extractor, version)。

**溯源链**(不变,复用 S0 全部基建):事实(带 evidence 时间戳)→ media_extraction(转写稿 full_text + result_json 含 segments/info)→ media_asset(sha256)→ 资产库原始音频字节;转写稿进 memory_log+FTS 可召回。

## 6. 安全与错误处理增量

- allowlist:`.wav → audio/wav`、`.mp3 → audio/mpeg`、`.m4a → audio/mp4`;音频单文件上限 500MB(独立于图像 50MB;1 小时会议 mp3 常超 50MB)。
- 缺 faster-whisper → `MissingDependencyError`,提示 `pip install "mase-memory[audio]"`。
- CUDA 不可用/DLL 缺失 → 明确 warning 后回退 `device=cpu, compute=int8`,不静默也不崩批。
- 损坏音频/解码失败 → 该文件落 infra_errors,批次继续(既有隔离机制)。

## 7. 测试与验收

**单元(不碰真 ASR/LLM)**:
- 接缝演化特征测试:S0 全部既有断言在 MediaPayload 形状下仍绿。
- `audio_transcriber`:假 WhisperModel(monkeypatch)→ 时间戳格式化/确定性拼稿;缺依赖报错。
- `audio_extractor`:假 transcriber + FakeModelInterface → JSON 契约解析、时间戳 evidence 校验、分块合并、降级路径。
- `ingest` 调度:audio 文件走 AudioExtractor、图像仍走 VisionExtractor;混合文件夹一次跑通。
- security:新扩展名/500MB 上限。

**验收(真模型,evidence 落 `E:/MASE-runs/s1_acceptance/<ts>/`)**:
- 样本:Windows SAPI TTS(System.Speech,离线)合成含锚词句子的 WAV(如 "the phoenix project budget is approved by acme"),真语音无网络依赖。
- 双 lane:`large-v3` 与 `large-v3-turbo` 各跑一遍;断言:转写稿含锚词、FTS 召回锚词、≥1 条事实带时间戳 evidence、溯源链走到资产字节。
- evidence.json/md 记:whisper 模型、device/compute、时长、转写摘录、事实抽样。
- **判定 PASS 前 S1 只标"待验收"**。

## 8. 风险

- **CUDA 依赖**:新版 ctranslate2 需 CUDA 12 + cuDNN 9;Windows 常需 `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` 补 DLL。实现时实测本机;GPU 不通则验收先跑 CPU int8 lane 并在 evidence 里如实标注,GPU lane 补验后再升级证据。
- **SAPI 中文语音**:本机若无中文 TTS voice,验收样本用英文锚词(FTS unicode61 对 ASCII 大小写不敏感,召回不受影响);中文真实录音验证留给用户实料。
- **转写方差**:whisper 对同音频跨版本可能有差异;evidence 记录 faster-whisper 与模型版本号,复跑以同版本为准。

## 9. 非目标(YAGNI)

说话人分离(diarization)、实时流式转写、麦克风录制、视频音轨(S3)、翻译、字幕导出。
