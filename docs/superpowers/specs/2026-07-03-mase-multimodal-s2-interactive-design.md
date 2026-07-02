# MASE 多模态能力 — S2 设计:交互式图像摄取、HTTP 上传与云视觉 provider

- 状态:草案(待用户审阅)
- 日期:2026-07-03
- 前置:S0 已验收(v0.5.0);S1 代码完成(验收进行中)。S0/S1 既定模式(资产库溯源、MediaPayload 接缝、抽取器调度、逐文件隔离、幂等、双门验收)直接沿用不重复。

---

## 1. 目标

用户在 MASE 控制台聊天页贴一张图 → 图片经 HTTP 上传进入 S0 摄取管线("看一次·记文字":资产库+抽取+溯源入库)→ 前端回显抽取结果卡片 → 后续对话由 executor 用已入库文本回答。同时补全引擎无关接缝:vision agent 可配置 OpenAI/Anthropic 兼容云模型做抽取(受现有云审批门控)。

## 2. 已定决策(用户模式代入,推荐项;审阅时可推翻)

| 决策点 | 选定 | 依据 |
|---|---|---|
| 交互形态 | **上传即摄取** | 图片不进模型对话上下文;走 S0 管线入库,对话用已治理文本——"先治理再注入"的直接延伸 |
| 云视觉序列化 | **做** | 补全引擎无关接缝;`_split_system_messages` 多模态透传修复即为此铺垫;受 `MASE_ALLOW_CLOUD_MODELS` 现有审批门控 |
| 前端范围 | **ChatPage 内嵌上传** | 上传按钮+拖放+抽取结果卡片;一个入口,改动面小;独立批量页不做(CLI 已覆盖批量) |

## 3. 架构增量

```
引擎层  src/mase/multimodal/
  image_message.py          【新】provider 感知的图像消息构造器(见 §4)
  vision_extractor.py       【改】图像消息构造下沉到 image_message;按 vision agent 的
                             effective provider 选序列化;其余行为不变(断言不改)

HTTP 层  integrations/openai_compat/
  media_routes.py           【新】POST /v1/mase/media/upload(见 §5)
  server.py                 【改】挂载 media_router(一行 include)

前端  frontend/src/
  pages/ChatPage.tsx        【改】上传按钮 + 拖放 → POST upload → 抽取结果卡片回显
  components/MediaIngestCard.tsx 【新】卡片:文件名/sha256 前 12 位/facts 列表/全文摘录/warnings
```

不新增 schema、不新增配置结构(vision agent 换云 provider = 改 `models.vision` 的 provider/base_url/api_key_env,纯配置)。

## 4. provider 感知图像消息(image_message.py)

已核实的三家请求体差异(2026-07 官方文档):

```python
def build_image_message(provider: str, prompt: str, pages: list[PageImage]) -> dict[str, Any]
```

- `ollama`(现状,唯一本地路径):`{"role":"user","content":prompt,"images":[<裸base64>...]}`
- `openai`:`content` 为 blocks:`[{"type":"text","text":prompt}, {"type":"image_url","image_url":{"url":"data:<mime>;base64,<b64>"}}, ...]`
- `anthropic`:`content` 为 blocks,**图在前文在后**(官方最佳实践):`[{"type":"image","source":{"type":"base64","media_type":"<mime>","data":"<b64>"}}, ..., {"type":"text","text":prompt}]`
- 其他 provider → `ValueError`(明确失败,不猜)。

`VisionExtractor.extract` 改为:每页调用前用 `model_interface.get_effective_agent_config("vision", mode)` 取 provider,交给 `build_image_message` 构造消息;Ollama 路径输出与现状逐字节一致(既有断言不改)。云 provider 调用自动经过 `_enforce_cloud_model_policy`(未批准即抛,S0 起就有)。

透传链已就绪:`_call_openai` 原样 post messages;`_call_anthropic` 的 `_split_system_messages` 已修为保留结构化 content(本特性最早的前置修复)。

## 5. 上传路由(media_routes.py)

```
POST /v1/mase/media/upload   (multipart/form-data, 字段 file;可选 form 字段 mode)
auth: Depends(require_internal_api_key);写记忆 → require_writable_mode()
```

流程(最大化复用,不造第二条管线):
1. 校验文件名扩展 ∈ `security.ALLOWED_MEDIA_TYPES` 且非音频(S2 只收图像/PDF;音频上传留待需要时开);
2. 流式读入,超 `default_max_bytes(media_type)` 即断开拒绝(413);
3. 写入每请求独立临时目录(`tempfile.mkdtemp` 于 runs 区)→ **直接调用 `ingest_folder(tmp_dir, mode=...)`**——jail/classify/资产库/调度/溯源/幂等全部复用;
4. 用响应字节的 sha256 反查 `get_media_asset(sha256=...)` + `find_extraction(...)` 组装响应;
5. 清理临时目录(资产库里已有内容寻址副本)。

响应形状:

```json
{
  "media_id": 7, "sha256": "…", "media_type": "image/png",
  "extraction": {"extractor": "vision", "model": "qwen2.5vl:7b", "version": "1",
                  "full_text_excerpt": "前 500 字…", "facts": [{"category":"…","key":"…","value":"…","evidence":"…"}],
                  "warnings": []},
  "deduplicated": false
}
```

安全边界:仅 multipart 直传字节;**不接受 URL(零 SSRF 面)**;大小上限先于落盘;临时目录在 runs 区且请求结束即删;审计——上传本身经 ingest 管线落 media_asset/media_extraction,天然可审计。同 sha 重复上传 → `deduplicated: true`,不重抽(幂等键沿用)。

## 6. 前端(ChatPage 内嵌)

- 输入区加"📎 上传"按钮 + 对话区拖放;选中文件后 `fetch("/v1/mase/media/upload", {method:"POST", body: FormData})`,鉴权复用 `frontend/src/api.ts` 现有 `getInternalApiKey()`(localStorage 持久化,已核实存在);后端 `require_internal_api_key` 在未配置 token 的本地开发态放行(现状语义,不改)。
- 成功 → 消息流插入 `MediaIngestCard`(assistant 侧):文件名、sha256 前 12 位、facts 表(category.key = value)、full_text 摘录(折叠展开)、warnings;失败 → 卡片显示错误与原因(类型/大小/服务端错误)。
- 上传后用户直接提问,现有 `/v1/chat/completions` → `mase_ask` 经记忆召回已入库事实回答——聊天链路零改动。
- Vitest:卡片渲染(facts/warnings/错误态)+ 上传函数(mock fetch)的成功/413/401 分支。

## 7. 测试与验收

**单元(不碰真模型/真服务)**:
- `image_message`:三家 payload 形状逐字段断言(ollama 与现状逐字节一致;openai data URI 前缀;anthropic 图前文后+media_type);未知 provider 抛错。
- `vision_extractor`:FakeModelInterface 增加 `get_effective_agent_config` 返回;现有断言不改,新增"provider=openai/anthropic 时消息形状"用例。
- `media_routes`:FastAPI TestClient + 假抽取器(monkeypatch `_default_extractors`):上传成功形状、重复上传 `deduplicated:true`、超限 413、坏扩展 415、缺 key 401、只读模式拒写。
- 前端 vitest(§6)。

**验收(evidence 落 `E:/MASE-runs/s2_acceptance/<ts>/`)**:
- **本地 lane(必须)**:真起 sidecar 服务(uvicorn 子进程)+ 真 Ollama qwen2.5vl:7b,httpx 真实 multipart 上传 S0 同款发票 PNG → 断言响应含锚词事实、溯源链完整、随后 `/v1/chat/completions` 问预算能召回。
- **云 lane(可选,如实标注)**:仅当用户显式设 `MASE_ALLOW_CLOUD_MODELS=1` 且配置了视觉能力云模型时跑;否则 evidence 标 `cloud_lane: skipped (not approved/configured)`,**不算 FAIL 也绝不冒充已验证**。云序列化的正确性底线由单元级 payload 形状测试(对照官方文档)保证。
- 前端以 vitest + typecheck + build 三门为准;浏览器人工冒烟由用户随需进行,不作为自动证据。

## 8. 风险与边界

- 云视觉模型选型不在本 spec 内定死(GLM-4V/Claude 等由用户配置);S2 只保证"配置了就能正确传图 + 审批门控生效"。
- 大 PDF 交互上传体验(多页抽取耗时)→ 同步返回,前端显示进行中;异步任务队列 YAGNI,不做。
- ChatPage.tsx 现为 448 行(已核实);改动控制在输入区与消息渲染两处,卡片做独立组件避免该文件继续膨胀。

## 9. 非目标(YAGNI)

URL 抓图、音频/视频上传路由、异步上传队列、多文件批量上传 UI(CLI 已覆盖批量)、直接多模态对话(图进 chat 上下文)、独立资料管理页。
