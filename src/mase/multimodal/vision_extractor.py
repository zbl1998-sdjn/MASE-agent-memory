"""本地 VLM 视觉抽取器 v2(两段式:忠实转写 → 文本 LLM 抽既定事实)。

v1(单段式,VLM 同时转写+抽事实)在真实扫描件上"读得懂但抽不全"
(dev 评测:SROIE 全文锚串 1.00 但事实锚串 0.28)。v2 与 S1 音频同构:
- 第一段:VLM 只负责逐字忠实转写(审计底稿),每页一调;
- 第二段:现有文本 LLM(config `doc_facts`)按严格 JSON 契约从底稿
  抽取全部具体业务事实,只允许引用原文,不允许推测——"在既定事实的
  基础上保证正确率和低幻觉率"。
引擎无关接缝不变:图像消息经 image_message 按 provider 序列化;云
provider 出网仍受 MASE_ALLOW_CLOUD_MODELS 审批门控。
"""
from __future__ import annotations

from typing import Any

from .document_loader import MediaPayload
from .extractor import ExtractionResult, MediaAssetInfo
from .image_message import build_image_message
from .text_facts import extract_facts_from_text

VISION_EXTRACTOR_VERSION = "3"

VISION_TRANSCRIBE_SYSTEM = """你是文档转写器。请逐字忠实转写图片中全部可读文本:
- 保留数字、单位、编号、日期的原始写法;
- 不要在字符之间插入多余空格;
- 按版面自上而下逐行输出,不要解释、不要总结、不要输出 JSON,只输出转写文本;
- 图片中没有可读文本时输出空行。"""

# 类别引导对齐 db_core.PROFILE_TEMPLATES;未知类别由 upsert_entity_fact 护栏归入 general_facts。
DOC_FACTS_SYSTEM = """你是企业文档事实抽取器。输入是一份文档的逐字转写稿。
请输出严格的 JSON(不要 markdown 代码围栏),形状:
{"facts": [{"category": "<user_preferences|people_relations|project_status|finance_budget|location_events|general_facts 之一>",
            "key": "<snake_case 唯一键>", "value": "<事实当前值>",
            "confidence": <0到1的数字>, "evidence": "<支撑该事实的转写稿原文片段>"}]}
规则:
- 系统性抽取全部具体业务事实;单据/票据/表单类文本中,以下要素只要出现就必须逐项抽取:
  商家或主体名称、完整地址、日期、单据编号、各项金额与税额、负责人/联系人、条款比例、期限;
- **value 必须逐字取自原文,严禁改写格式**:日期照抄原文写法(如原文 12/28/2017 就写 12/28/2017,
  不得改成 2017-12-28),金额、编号同理保持原样;
- 表单勾选项(√/☑ 选中,□ 未选)只抽取被选中的值,未选中的选项不是事实;
- 只抽取转写稿中明确出现的内容,evidence 必须引用原文,严禁推测或补全;
- 口号、标语、栏目标题、装饰文字(如"创新·协作·卓越"、"Culture wall")不是业务事实,不要抽取;
- 页面只有名称/口号等装饰内容而无任何业务数据时,返回 {"facts": []}。"""


class VisionExtractor:
    """把页图转成"忠实转写 + 既定事实"的可审计 ExtractionResult(两段式)。"""

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
        vlm_model = "unknown"
        agent_config = self.model_interface.get_effective_agent_config("vision", mode=self.mode)
        provider = str(agent_config.get("provider") or "ollama")

        # 第一段:每页忠实转写(审计底稿)
        for page in pages:
            prompt = (
                f"来源: {asset.source_uri or asset.sha256[:12]}"
                f" 第 {page.index + 1}/{asset.page_count} 页。请按系统提示转写。"
            )
            message = build_image_message(provider, prompt, page)
            response = self.model_interface.chat(
                "vision",
                messages=[message],
                mode=self.mode,
                override_system_prompt=VISION_TRANSCRIBE_SYSTEM,
            )
            vlm_model = str(response.get("model") or vlm_model)
            page_text = str((response.get("message") or {}).get("content") or "").strip()
            if page.index > 0:
                text_parts.append(f"--- page {page.index + 1} ---")
            text_parts.append(page_text)

        full_text = "\n\n".join(part for part in text_parts if part).strip()

        # 第二段:文本 LLM 从底稿抽既定事实
        facts, warnings, llm_model = extract_facts_from_text(
            self.model_interface,
            agent_type="doc_facts",
            system_prompt=DOC_FACTS_SYSTEM,
            text=full_text,
        )

        return ExtractionResult(
            full_text=full_text,
            candidate_facts=tuple(facts),
            extractor_name=self.name,
            model_name=f"{vlm_model}+{llm_model}",
            extractor_version=self.version,
            warnings=tuple(warnings),
        )
