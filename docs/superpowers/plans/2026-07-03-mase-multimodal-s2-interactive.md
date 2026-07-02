# MASE S2 交互式图像摄取 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChatPage 贴图 → HTTP 上传 → S0 摄取管线入库(溯源)→ 前端抽取结果卡片回显;vision agent 可配置 OpenAI/Anthropic 兼容云模型(受现有云审批门控)。

**Architecture:** 三层增量:①`image_message.py` provider 感知图像消息构造(ollama/openai/anthropic 三家序列化,vision_extractor 按 effective provider 选);②`media_routes.py` multipart 上传路由,内部直接调 `ingest_folder`(复用 jail/资产库/调度/溯源/幂等,不造第二条管线);③前端 `api.uploadMedia` + `MediaIngestCard` + ChatPage 内嵌上传。

**Tech Stack:** FastAPI UploadFile(python-multipart 0.0.32 已装)、httpx(验收)、React19+vitest(前端)。无新增必装依赖(python-multipart 补进 `server` extra 钉版本)。

**Spec:** `docs/superpowers/specs/2026-07-03-mase-multimodal-s2-interactive-design.md`(已批准)。

## Global Constraints

- Conventional Commits;一特性一提交;禁 `--no-verify`;尾行 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`;多行消息用 Write 写文件 + `git commit -F`。
- 红→绿→提交;单元测试不碰真模型/真服务进程;S0/S1 既有断言不改。
- 测试隔离:`MASE_DB_PATH` + `MASE_MEDIA_ASSETS_DIR` 指 tmp_path;auth 相关用 `monkeypatch.setenv("MASE_INTERNAL_API_KEY", ...)` / `MASE_READ_ONLY`。
- 传图格式(2026-07 官方文档核验):ollama=message 级 `images:[裸b64]`;openai=`content` blocks `image_url` data URI;anthropic=`content` blocks `image` source,**图前文后**。
- 全量测试:`python -m pytest -q -m "not integration and not slow"`(基线 695);前端 `npm --prefix frontend test`(基线 38)。
- ⚠️ 本任务开工前提:S1 验收已收口(深度优先)。

---

### Task 1: image_message.py — provider 感知图像消息构造器

**Files:**
- Create: `src/mase/multimodal/image_message.py`
- Modify: `src/mase/multimodal/vision_extractor.py`(消息构造下沉;按 provider 选)
- Modify: `tests/test_vision_extractor.py`(FakeModelInterface 补 `get_effective_agent_config`;新增 provider 形状用例;既有断言不改)
- Test: `tests/test_image_message.py`

**Interfaces:**
- Produces:
  - `build_image_message(provider: str, prompt: str, page: PageImage) -> dict[str, Any]`(单页,匹配现有每页一调的模式;未知 provider 抛 ValueError)
  - vision_extractor 内:`provider = str(self.model_interface.get_effective_agent_config("vision", mode=self.mode).get("provider") or "ollama")`,每页 `message = build_image_message(provider, prompt, page)`
- Consumes: `ModelInterface.get_effective_agent_config(agent_type, mode)`(现有);`PageImage`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_image_message.py
"""provider 感知图像消息:三家序列化形状 + 未知 provider 拒绝。"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.document_loader import PageImage

_PAGE = PageImage(0, b"\x89PNGfake", "image/png")
_B64 = base64.b64encode(b"\x89PNGfake").decode("ascii")


def test_ollama_shape_images_sibling_field():
    from mase.multimodal.image_message import build_image_message

    msg = build_image_message("ollama", "请抽取", _PAGE)
    assert msg == {"role": "user", "content": "请抽取", "images": [_B64]}


def test_openai_shape_data_uri_blocks():
    from mase.multimodal.image_message import build_image_message

    msg = build_image_message("openai", "extract", _PAGE)
    assert msg["role"] == "user"
    assert msg["content"][0] == {"type": "text", "text": "extract"}
    assert msg["content"][1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{_B64}"},
    }


def test_anthropic_shape_image_before_text():
    from mase.multimodal.image_message import build_image_message

    msg = build_image_message("anthropic", "extract", _PAGE)
    assert msg["role"] == "user"
    # Anthropic 官方最佳实践:图在前文在后
    assert msg["content"][0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": _B64},
    }
    assert msg["content"][1] == {"type": "text", "text": "extract"}


def test_unknown_provider_rejected():
    from mase.multimodal.image_message import build_image_message

    with pytest.raises(ValueError, match="llama_cpp"):
        build_image_message("llama_cpp", "p", _PAGE)
```

- [ ] **Step 2: 确认红**

Run: `python -m pytest tests/test_image_message.py -q`
Expected: FAIL — `No module named 'mase.multimodal.image_message'`

- [ ] **Step 3: 实现 image_message.py**

```python
"""provider 感知的图像消息构造器(引擎无关接缝的序列化端)。

三家请求体差异(2026-07 官方文档核验):
- ollama:  message 级 ``images: [<裸base64>]`` 兄弟字段(docs/api.md)
- openai:  content blocks ``image_url`` + data URI(developers.openai.com)
- anthropic: content blocks ``image`` source,图前文后(platform.claude.com vision)
云 provider 的实际调用仍经 model_interface 的云审批门控,这里只管形状。
"""
from __future__ import annotations

import base64
from typing import Any

from .document_loader import PageImage


def build_image_message(provider: str, prompt: str, page: PageImage) -> dict[str, Any]:
    """把"提示词 + 单页图"序列化成目标 provider 的 user 消息。"""
    b64 = base64.b64encode(page.image_bytes).decode("ascii")
    normalized = str(provider or "").strip().lower()
    if normalized == "ollama":
        return {"role": "user", "content": prompt, "images": [b64]}
    if normalized == "openai":
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{page.media_type};base64,{b64}"}},
            ],
        }
    if normalized == "anthropic":
        return {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": page.media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }
    raise ValueError(f"不支持的视觉 provider: {provider!r}(支持 ollama/openai/anthropic)")
```

- [ ] **Step 4: vision_extractor 下沉消息构造**

import 加 `from .image_message import build_image_message`;`extract` 循环内原 message 字典构造:

```python
            message = {
                "role": "user",
                "content": prompt,
                # Ollama chat 多模态约定:base64 图放 message 级 images 兄弟字段
                "images": [base64.b64encode(page.image_bytes).decode("ascii")],
            }
```

改为(方法体循环外先取一次 provider):

```python
        agent_config = self.model_interface.get_effective_agent_config("vision", mode=self.mode)
        provider = str(agent_config.get("provider") or "ollama")
```

循环内:

```python
            message = build_image_message(provider, prompt, page)
```

删除本文件 `import base64`(若不再使用)。

- [ ] **Step 5: 既有测试补 fake 方法 + 新增 provider 用例**

`tests/test_vision_extractor.py` 的 `FakeModelInterface` 加:

```python
    provider = "ollama"

    def get_effective_agent_config(self, agent_type, mode=None):
        return {"provider": self.provider, "model_name": "fake-vlm"}
```

文件尾部追加:

```python
def test_openai_provider_builds_content_blocks():
    """provider=openai 时消息为 image_url blocks(引擎无关接缝的云路径)。"""
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface([json.dumps({"full_text": "t", "facts": []})])
    fake.provider = "openai"
    VisionExtractor(fake).extract(_asset(), _pages(PageImage(0, b"i", "image/png")))
    content = fake.calls[0]["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
```

既有 5 个用例断言不动(fake 默认 ollama,消息形状与现状逐字节一致)。

- [ ] **Step 6: 全绿 + 提交**

Run: `python -m pytest tests/test_image_message.py tests/test_vision_extractor.py -q` → 4+7=11 passed
Run: `python -m pytest -q -m "not integration and not slow"` → 700 passed(695+5)
Run: `python -m ruff check . && python -m mypy` → 干净

提交消息(Write→`git commit -F`):

```
feat(multimodal): provider-aware image message serialization

build_image_message maps the engine-agnostic page+prompt onto the
Ollama images sibling field, OpenAI image_url data-URI blocks, or
Anthropic image-before-text source blocks (shapes verified against
2026-07 official docs). VisionExtractor picks the serializer from the
vision agent's effective provider; cloud calls remain gated by the
existing MASE_ALLOW_CLOUD_MODELS policy. Ollama path byte-identical.
```

```bash
git add src/mase/multimodal/image_message.py src/mase/multimodal/vision_extractor.py tests/test_image_message.py tests/test_vision_extractor.py
git commit -F <消息文件>
```

---

### Task 2: 上传路由 media_routes.py

**Files:**
- Create: `integrations/openai_compat/media_routes.py`
- Modify: `integrations/openai_compat/server.py`(import + `app.include_router(media_router)`,紧邻 memory_router 处)
- Modify: `pyproject.toml`(`server` extra 加 `"python-multipart>=0.0.9,<1.0"`;已装 0.0.32,仅钉声明)
- Test: `tests/test_media_routes.py`

**Interfaces:**
- Produces:`POST /v1/mase/media/upload`(multipart 字段 `file`,可选 form 字段 `mode`);响应 §spec5 形状;错误码:415 坏类型 / 413 超限 / 401 配置 token 后缺 key / 403 只读模式
- Consumes:`ingest_folder`(monkeypatch 点:`media_routes.ingest_folder` 不必——测试走 `mase.multimodal.ingest._default_extractors` monkeypatch + 真 `ingest_folder`);`security.ALLOWED_MEDIA_TYPES/default_max_bytes`;`get_media_asset(sha256=)/find_extraction`;`require_internal_api_key/require_writable_mode`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_media_routes.py
"""上传路由:真管线+假抽取器;鉴权/只读/类型/大小/去重分支。"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient

from mase.multimodal.extractor import CandidateFact, ExtractionResult


class _FakeVision:
    name, version = "vision", "1"

    def supports(self, media_type):
        return media_type.startswith("image/") or media_type == "application/pdf"

    def extract(self, asset, payload):
        return ExtractionResult(
            full_text="INVOICE ACME-INV-2026-001 total 4200 EUR",
            candidate_facts=(
                CandidateFact("finance_budget", "invoice_total", "4200 EUR", 0.9, "total 4200 EUR"),
            ),
            extractor_name="vision", model_name="fake-vlm", extractor_version="1", warnings=(),
        )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.delenv("MASE_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("MASE_READ_ONLY", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "media_routes.db"))
    monkeypatch.setenv("MASE_MEDIA_ASSETS_DIR", str(tmp_path / "assets"))
    from mase.multimodal import ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "_default_extractors", lambda mode, whisper_model: [_FakeVision()])
    from integrations.openai_compat.server import app

    return TestClient(app)


def test_upload_ingests_and_returns_extraction(client, tmp_path):
    data = b"\x89PNG-s2-invoice"
    resp = client.post(
        "/v1/mase/media/upload",
        files={"file": ("invoice.png", data, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["media_type"] == "image/png"
    assert body["deduplicated"] is False
    assert body["extraction"]["facts"][0]["key"] == "invoice_total"
    assert "ACME-INV-2026-001" in body["extraction"]["full_text_excerpt"]
    assert isinstance(body["media_id"], int)


def test_duplicate_upload_is_deduplicated(client):
    data = b"same-image-bytes"
    files = {"file": ("a.png", data, "image/png")}
    first = client.post("/v1/mase/media/upload", files=files)
    second = client.post("/v1/mase/media/upload", files=files)
    assert first.json()["deduplicated"] is False
    assert second.json()["deduplicated"] is True
    assert second.json()["media_id"] == first.json()["media_id"]


def test_bad_extension_rejected_415(client):
    resp = client.post("/v1/mase/media/upload", files={"file": ("evil.exe", b"MZ", "application/octet-stream")})
    assert resp.status_code == 415


def test_audio_upload_rejected_415(client):
    """S2 上传只收图像/PDF;音频批处理走 CLI(spec §5)。"""
    resp = client.post("/v1/mase/media/upload", files={"file": ("m.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 415


def test_oversize_rejected_413(client, monkeypatch):
    from mase.multimodal import security

    monkeypatch.setattr(security, "DEFAULT_MAX_BYTES", 16)
    resp = client.post("/v1/mase/media/upload", files={"file": ("big.png", b"x" * 64, "image/png")})
    assert resp.status_code == 413


def test_requires_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("MASE_INTERNAL_API_KEY", "test-internal-key")  # allowlist-secret
    resp = client.post("/v1/mase/media/upload", files={"file": ("a.png", b"x", "image/png")})
    assert resp.status_code == 401


def test_read_only_mode_rejects_403(client, monkeypatch):
    monkeypatch.setenv("MASE_READ_ONLY", "1")
    resp = client.post("/v1/mase/media/upload", files={"file": ("a.png", b"x", "image/png")})
    assert resp.status_code == 403
```

- [ ] **Step 2: 确认红**

Run: `python -m pytest tests/test_media_routes.py -q`
Expected: 7 项全 FAIL(404 Not Found — 路由不存在)

- [ ] **Step 3: 实现 media_routes.py**

```python
"""交互式媒体上传路由(S2):multipart → S0 摄取管线 → 抽取结果回显。

只收图像/PDF 直传字节;不接受 URL(零 SSRF 面);大小上限先于落盘;
临时目录请求结束即删(资产库已有内容寻址副本)。写记忆 → 只读模式拒绝,
配置 token 后必须带 key。
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from integrations.openai_compat.auth_dependencies import require_internal_api_key, require_writable_mode
from mase.multimodal.ingest import ingest_folder
from mase.multimodal.security import ALLOWED_MEDIA_TYPES, default_max_bytes
from mase_tools.memory.media_records import find_extraction, get_media_asset

router = APIRouter()

_EXCERPT_CHARS = 500
_CHUNK = 1 * 1024 * 1024


@router.post("/v1/mase/media/upload")
def upload_media(
    file: UploadFile,
    mode: str | None = Form(default=None),
    _auth: None = Depends(require_internal_api_key),
) -> dict[str, Any]:
    require_writable_mode()

    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    media_type = ALLOWED_MEDIA_TYPES.get(suffix)
    if media_type is None or media_type.startswith("audio/"):
        # S2 交互上传只收图像/PDF;音频批量入库走 CLI(spec §5/§9)。
        raise HTTPException(status_code=415, detail=f"unsupported media type: {suffix!r}")

    max_bytes = default_max_bytes(media_type)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = file.file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"file exceeds {max_bytes} bytes")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    sha256 = hashlib.sha256(data).hexdigest()

    # 幂等预检:同哈希且同版本已抽取 → 不重跑管线,直接回显既有抽取。
    existing = get_media_asset(sha256=sha256)
    deduplicated = False

    tmp_dir = Path(tempfile.mkdtemp(prefix="mase_upload_"))
    try:
        (tmp_dir / filename).write_bytes(data)
        report = ingest_folder(tmp_dir, mode=mode)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if report.infra_errors:
        raise HTTPException(status_code=502, detail={"infra_errors": list(report.infra_errors)})
    if existing is not None and any(s.get("reason") == "already_extracted" for s in report.skipped):
        deduplicated = True

    asset = get_media_asset(sha256=sha256)
    if asset is None:
        raise HTTPException(status_code=502, detail="asset registration missing after ingest")
    extraction = find_extraction(int(asset["id"]), extractor_name="vision", extractor_version="1")
    if extraction is None:
        raise HTTPException(status_code=502, detail="extraction record missing after ingest")

    import json as _json

    result_json = _json.loads(extraction.get("result_json") or "{}")
    return {
        "media_id": int(asset["id"]),
        "sha256": sha256,
        "media_type": media_type,
        "deduplicated": deduplicated,
        "extraction": {
            "extractor": extraction["extractor_name"],
            "model": extraction["model_name"],
            "version": extraction["extractor_version"],
            "full_text_excerpt": str(extraction.get("full_text") or "")[:_EXCERPT_CHARS],
            "facts": result_json.get("candidate_facts", []),
            "warnings": result_json.get("warnings", []),
        },
    }
```

⚠️ 实现校验点:`find_extraction` 的 `extractor_name="vision"` 写死与 VisionExtractor.name 一致;若上传 PDF 也走 vision(supports 含 application/pdf)成立。`require_internal_api_key` 无 key 未配置时放行——`test_requires_key_when_configured` 里设了 env 后 `get_auth_context` 应 401(以 auth_dependencies 实际行为为准,若返回 403 调整断言并在提交信息注明)。

- [ ] **Step 4: server.py 挂载**

import 区(memory_routes import 旁)加:

```python
from integrations.openai_compat.media_routes import (
    router as media_router,
)
```

`app.include_router(memory_router)` 旁加 `app.include_router(media_router)`(以 server.py 实际 include 位置为锚)。

- [ ] **Step 5: pyproject server extra 钉 multipart**

```toml
server = [
    "fastapi>=0.110,<1.0",
    "uvicorn>=0.27,<1.0",
    "python-multipart>=0.0.9,<1.0",
]
```

(`all` 与 `dev` 若含 fastapi 同步补。)

- [ ] **Step 6: 全绿 + 提交**

Run: `python -m pytest tests/test_media_routes.py -q` → 7 passed
Run: `python -m pytest -q -m "not integration and not slow"` → 707 passed
Run: `python -m ruff check . && python -m mypy` → 干净

提交消息:

```
feat(multimodal): interactive media upload route reusing ingest pipeline

POST /v1/mase/media/upload (multipart, images/PDF only, no URL fetch):
size cap enforced before disk write, per-request temp dir feeds
ingest_folder so jail/asset-store/dispatch/provenance/idempotency are
all reused; response returns extraction facts + excerpt + dedup flag.
Guarded by internal-key auth and read-only mode.
```

```bash
git add integrations/openai_compat/media_routes.py integrations/openai_compat/server.py pyproject.toml tests/test_media_routes.py
git commit -F <消息文件>
```

---

### Task 3: 前端 — api.uploadMedia + MediaIngestCard + ChatPage 内嵌

**Files:**
- Modify: `frontend/src/api.ts`(加 uploadMedia + 类型)
- Modify: `frontend/src/types.ts`(加 MediaUploadData)
- Create: `frontend/src/components/MediaIngestCard.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx`(上传按钮 + 拖放 + 卡片消息)
- Test: `frontend/src/components/MediaIngestCard.test.tsx`、`frontend/src/api.test.ts`(追加)

**Interfaces:**
- `types.ts`:

```typescript
export interface MediaUploadFact {
  category: string;
  key: string;
  value: string;
  confidence: number;
  evidence: string;
}

export interface MediaUploadData {
  media_id: number;
  sha256: string;
  media_type: string;
  deduplicated: boolean;
  extraction: {
    extractor: string;
    model: string;
    version: string;
    full_text_excerpt: string;
    facts: MediaUploadFact[];
    warnings: string[];
  };
}
```

- `api.ts`(multipart 不能带 JSON Content-Type,绕过 `request<T>`,复用 `authHeaders()`):

```typescript
export async function uploadMedia(file: File, mode?: string): Promise<MediaUploadData> {
  // multipart 由浏览器自动设置 boundary;绝不能手动设 Content-Type。
  const form = new FormData();
  form.append("file", file);
  if (mode) form.append("mode", mode);
  const response = await fetch(`${API_BASE}/v1/mase/media/upload`, {
    method: "POST",
    headers: { ...authHeaders() },
    body: form
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return response.json() as Promise<MediaUploadData>;
}
```

- `MediaIngestCard.tsx`:props `{ fileName: string; data?: MediaUploadData; error?: string }`;渲染:文件名、`sha256.slice(0, 12)`、`deduplicated` 标记、facts 表(category.key = value)、full_text_excerpt(`<details>` 折叠)、warnings 列表;error 态只渲染错误行。
- `ChatPage.tsx`:消息列表类型改本地联合 `type ChatEntry = ChatMessage | { role: "media"; fileName: string; data?: MediaUploadData; error?: string }`;输入区加 `📎` 按钮触发隐藏 `<input type="file" accept=".png,.jpg,.jpeg,.webp,.gif,.pdf">`;对话容器 `onDrop/onDragOver`;上传中在列表放 pending 卡片,完成后原位更新;渲染分支 `entry.role === "media" ? <MediaIngestCard .../> : 现有气泡`。

- [ ] **Step 1: 写失败测试(vitest)**

```typescript
// frontend/src/components/MediaIngestCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MediaIngestCard } from "./MediaIngestCard";

const data = {
  media_id: 7,
  sha256: "abcdef0123456789".repeat(4),
  media_type: "image/png",
  deduplicated: false,
  extraction: {
    extractor: "vision", model: "qwen2.5vl:7b", version: "1",
    full_text_excerpt: "INVOICE ACME-INV-2026-001",
    facts: [{ category: "finance_budget", key: "invoice_total", value: "4200 EUR", confidence: 0.9, evidence: "total 4200 EUR" }],
    warnings: ["page 1: low confidence"]
  }
};

describe("MediaIngestCard", () => {
  it("renders facts, sha prefix and excerpt", () => {
    render(<MediaIngestCard fileName="invoice.png" data={data} />);
    expect(screen.getByText(/invoice\.png/)).toBeTruthy();
    expect(screen.getByText(/abcdef012345/)).toBeTruthy();
    expect(screen.getByText(/finance_budget\.invoice_total/)).toBeTruthy();
    expect(screen.getByText(/4200 EUR/)).toBeTruthy();
    expect(screen.getByText(/low confidence/)).toBeTruthy();
  });

  it("renders dedup marker", () => {
    render(<MediaIngestCard fileName="a.png" data={{ ...data, deduplicated: true }} />);
    expect(screen.getByText(/已入库|deduplicated/i)).toBeTruthy();
  });

  it("renders error state", () => {
    render(<MediaIngestCard fileName="bad.exe" error="415: unsupported media type" />);
    expect(screen.getByText(/415/)).toBeTruthy();
  });
});
```

`frontend/src/api.test.ts` 追加(照该文件既有 mock fetch 风格):

```typescript
it("uploadMedia posts FormData without JSON content-type", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ media_id: 1, sha256: "x", media_type: "image/png", deduplicated: false,
      extraction: { extractor: "vision", model: "m", version: "1", full_text_excerpt: "", facts: [], warnings: [] } })
  });
  vi.stubGlobal("fetch", fetchMock);
  const { uploadMedia } = await import("./api");
  await uploadMedia(new File([new Uint8Array([1])], "a.png", { type: "image/png" }));
  const [url, init] = fetchMock.mock.calls[0];
  expect(String(url)).toContain("/v1/mase/media/upload");
  expect(init.body).toBeInstanceOf(FormData);
  expect(init.headers?.["Content-Type"]).toBeUndefined();
});
```

(以 api.test.ts 现有 stub/reset 模式为准调整;若无 @testing-library/react 依赖则 `npm --prefix frontend i -D @testing-library/react`,并入本任务提交。)

- [ ] **Step 2: 确认红**

Run: `npm --prefix frontend test` → 新增用例 FAIL(模块不存在)

- [ ] **Step 3: 实现**(types.ts / api.ts / MediaIngestCard.tsx / ChatPage.tsx 按 Interfaces 块代码落地;ChatPage 上传处理函数:)

```typescript
async function handleFiles(files: FileList | null) {
  if (!files || files.length === 0) return;
  const file = files[0];
  const pendingIndex = entries.length;
  setEntries((prev) => [...prev, { role: "media", fileName: file.name }]);
  try {
    const data = await uploadMedia(file);
    setEntries((prev) => prev.map((e, i) => (i === pendingIndex ? { role: "media", fileName: file.name, data } : e)));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setEntries((prev) => prev.map((e, i) => (i === pendingIndex ? { role: "media", fileName: file.name, error: message } : e)));
  }
}
```

(state 命名以 ChatPage 现有 `messages` 状态实际改名/包装为准,聊天发送逻辑对 media 条目过滤——发给 `/v1/chat/completions` 的 messages 仅含 role user/assistant 条目,断言进 vitest?聊天过滤逻辑简单,由 typecheck+现有聊天行为回归覆盖。)

- [ ] **Step 4: 前端三门 + 提交**

Run: `npm --prefix frontend run typecheck && npm --prefix frontend test && npm --prefix frontend run build` → 全绿(测试 38+4=42 左右)

提交消息:

```
feat(frontend): inline media upload with extraction card in ChatPage

Upload button + drag-drop posts multipart to /v1/mase/media/upload via
the existing internal-key auth helper; MediaIngestCard echoes facts,
sha256 prefix, excerpt, warnings and dedup/error states. Chat send
path filters media entries so /v1/chat/completions payload is
unchanged.
```

```bash
git add frontend/src/api.ts frontend/src/types.ts frontend/src/components/MediaIngestCard.tsx frontend/src/components/MediaIngestCard.test.tsx frontend/src/pages/ChatPage.tsx frontend/package.json frontend/package-lock.json frontend/src/api.test.ts
git commit -F <消息文件>
```

---

### Task 4: S2 验收 harness + 全量门禁 + 真跑

**Files:**
- Create: `scripts/run_s2_acceptance.py`

**Interfaces(harness 行为):**
1. 依赖检查:Ollama 有 `qwen2.5vl:7b`(缺 → exit 2 给 pull 指引)。
2. 独立 evidence 目录 `<runs>/s2_acceptance/<ts>/`;env `MASE_DB_PATH/MASE_MEDIA_ASSETS_DIR` 指进去后,**uvicorn 子进程**起 `integrations.openai_compat.server:app`(随机高位端口),轮询 `/health` 就绪(超时 60s FAIL)。
3. PyMuPDF 生成 S0 同款发票 PNG(锚词 `ACME-INV-2026-001` / `4200`)。
4. httpx 真 multipart 上传 → 断言 200、facts 非空、excerpt 含锚词、`deduplicated:false`;重复上传断言 `deduplicated:true`。
5. `POST /v1/memory/recall`(body `{"query": "ACME-INV-2026-001", "top_k": 5}`,形状以 `schemas.MemoryRecallRequest` 为准)→ 断言召回命中锚词。
6. `POST /v1/chat/completions` 问 "What is the invoice total?" → 回答记入 evidence 作诊断字段(**不作为 PASS 判据**,7B 生成有措辞方差;PASS 判据是 4/5 两条)。
7. 溯源链抽样(复制 S0/S1 harness 的 `_check_provenance_chain`)。
8. **云 lane**:若 `MASE_ALLOW_CLOUD_MODELS` 未设或 vision agent provider 非云 → evidence 记 `cloud_lane: "skipped (not approved/configured)"`,不算 FAIL;否则以云 provider 重复步骤 4(单独 DB)。
9. evidence.json/md;PASS→0,FAIL→1,依赖缺失→2;结束时终止 uvicorn 子进程(finally 保证)。

- [ ] **Step 1: 实现 harness**(骨架同 run_s0/s1_acceptance.py,新增部分:uvicorn 子进程管理)

```python
def start_server(port: int, env: dict) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "uvicorn",
         "integrations.openai_compat.server:app", "--host", "127.0.0.1", "--port", str(port)],
        env={**os.environ, **env}, cwd=str(_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError("server exited early")
        time.sleep(1.0)
    proc.terminate()
    raise RuntimeError("server not ready in 60s")
```

(其余按 Interfaces 1-9 展开;所有断言失败打印具体差异;`finally: proc.terminate(); proc.wait(timeout=10)`。)

- [ ] **Step 2: 全量门禁**(README 集,含前端三门)→ 全绿

- [ ] **Step 3: 提交 harness**

```bash
git add scripts/run_s2_acceptance.py
git commit -m "feat(multimodal): S2 acceptance harness with live sidecar upload"
```

- [ ] **Step 4: 真跑验收**

```bash
python -X utf8 scripts/run_s2_acceptance.py --runs-dir E:/MASE-runs
```
Expected: `verdict=PASS`(本地 lane;cloud lane 如实 skipped)。**未 PASS 前 S2 只标"待验收"。**

- [ ] **Step 5: 收口**:CHANGELOG `[0.7.0]` + spec 状态行,各自独立 docs 提交;tag 由用户决定。

---

## Self-Review(已执行)

1. **Spec 覆盖**:§4 image_message → T1;§5 上传路由(流式限长/临时目录/幂等回显/错误码)→ T2;§6 前端(api/卡片/ChatPage/vitest)→ T3;§7 验收(本地必须/云可选如实标注/recall 判据)→ T4;§8 风险(同步返回/卡片独立组件)→ T3 设计;§9 非目标未越界。无缺口。
2. **占位符**:T3 Step 3 的 ChatPage state 命名与 T4 harness 展开处均给了锚点与判据,非悬空 TBD;关键代码全部在场。
3. **类型一致性**:`build_image_message(provider, prompt, page)` T1 测试↔实现一致;`MediaUploadData` T3 types↔api↔卡片一致;路由响应字段 T2 实现↔T3 类型↔T4 断言一致(`media_id/sha256/media_type/deduplicated/extraction.{extractor,model,version,full_text_excerpt,facts,warnings}`);auth env 名(`MASE_INTERNAL_API_KEY`/`MASE_READ_ONLY`)与 auth_dependencies.py 实际一致(已核实)。
