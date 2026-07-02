"""本地 VLM 视觉抽取器(S0 参考模态)。

引擎无关约定:抽取器只构造"文本提示 + 页图字节"的抽象请求;当前唯一
序列化目标是 Ollama chat 的 message 级 ``images:[base64]`` 兄弟字段
(官方 docs/api.md,裸 base64 无 data URI 前缀)。S2 在同一接缝扩展
OpenAI image_url / Anthropic image block。

提示词与解析器刻意同居本模块:JSON 输出契约变更时两者一起改。
"""
from __future__ import annotations

import base64
from typing import Any

from .document_loader import MediaPayload
from .extractor import (
    CandidateFact,
    ExtractionResult,
    MediaAssetInfo,
    coerce_confidence,
    parse_json_blob,
)

VISION_EXTRACTOR_VERSION = "1"

# 类别引导对齐 db_core.PROFILE_TEMPLATES;未知类别由 upsert_entity_fact
# 的既有护栏归入 general_facts,这里不重复实现。
VISION_EXTRACTION_SYSTEM = """你是企业文档抽取器。请仔细阅读图片并输出严格的 JSON(不要 markdown 代码围栏),形状:
{"full_text": "<转写图中全部可读文本,保留数字与单位>",
 "facts": [{"category": "<user_preferences|people_relations|project_status|finance_budget|location_events|general_facts 之一>",
            "key": "<snake_case 唯一键>", "value": "<事实当前值>",
            "confidence": <0到1的数字>, "evidence": "<full_text 中支撑该事实的原文片段>"}]}
规则:
- full_text 必须尽量完整转写,这是审计底稿;
- 只提取图中明确出现的事实,不要推测;没有事实就返回空数组;
- evidence 必须是 full_text 的子串级别引用。"""


class VisionExtractor:
    """把页图交给本地 VLM,产出可审计 ExtractionResult。"""

    name = "vision"
    version = VISION_EXTRACTOR_VERSION

    def __init__(self, model_interface: Any = None, *, mode: str | None = None) -> None:
        if model_interface is None:
            from mase.model_interface import ModelInterface

            model_interface = ModelInterface()
        self.model_interface = model_interface
        self.mode = mode

    def supports(self, media_type: str) -> bool:
        return media_type.startswith("image/") or media_type == "application/pdf"

    def extract(self, asset: MediaAssetInfo, payload: MediaPayload) -> ExtractionResult:
        pages = payload.pages
        text_parts: list[str] = []
        facts: list[CandidateFact] = []
        warnings: list[str] = []
        model_name = "unknown"

        for page in pages:
            prompt = (
                f"来源: {asset.source_uri or asset.sha256[:12]}"
                f" 第 {page.index + 1}/{asset.page_count} 页。请按系统提示抽取。"
            )
            message = {
                "role": "user",
                "content": prompt,
                # Ollama chat 多模态约定:base64 图放 message 级 images 兄弟字段
                "images": [base64.b64encode(page.image_bytes).decode("ascii")],
            }
            response = self.model_interface.chat(
                "vision",
                messages=[message],
                mode=self.mode,
                override_system_prompt=VISION_EXTRACTION_SYSTEM,
            )
            model_name = str(response.get("model") or model_name)
            raw = str((response.get("message") or {}).get("content") or "")
            page_text, page_facts, page_warnings = _parse_page_reply(raw, page_number=page.index + 1)
            if page.index > 0:
                text_parts.append(f"--- page {page.index + 1} ---")
            text_parts.append(page_text)
            facts.extend(page_facts)
            warnings.extend(page_warnings)

        return ExtractionResult(
            full_text="\n\n".join(part for part in text_parts if part).strip(),
            candidate_facts=tuple(facts),
            extractor_name=self.name,
            model_name=model_name,
            extractor_version=self.version,
            warnings=tuple(warnings),
        )


def _parse_page_reply(raw: str, *, page_number: int) -> tuple[str, list[CandidateFact], list[str]]:
    """解析单页模型回复;畸形输出降级为"原文即全文",绝不抛穿。"""
    reply = parse_json_blob(raw)
    if reply is not None:
        full_text = str(reply.get("full_text") or "").strip()
        facts = [
            CandidateFact(
                category=str(item.get("category") or "general_facts"),
                key=str(item.get("key") or "").strip(),
                value=str(item.get("value") or "").strip(),
                confidence=coerce_confidence(item.get("confidence")),
                evidence=str(item.get("evidence") or "").strip(),
            )
            for item in (reply.get("facts") or [])
            if isinstance(item, dict) and str(item.get("key") or "").strip() and str(item.get("value") or "").strip()
        ]
        return full_text or raw.strip(), facts, []
    return raw.strip(), [], [f"page {page_number}: non_json_response"]
