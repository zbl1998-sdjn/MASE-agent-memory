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
from .kv_extract import parse_kv_lines, union_kv_facts
from .structure_facts import parse_structure_facts, union_superset_facts
from .text_facts import extract_facts_from_text
from .transient_retry import call_with_transient_retry

VISION_EXTRACTOR_VERSION = "7"  # v7: 视觉补看轮 + 版面结构解析并集 + 选项组整组保留

VISION_TRANSCRIBE_SYSTEM = """你是文档转写器。请逐字忠实转写图片中全部可读文本:
- 保留数字、单位、编号、日期的原始写法;
- 不要在字符之间插入多余空格;
- 按版面自上而下逐行输出,不要解释、不要总结、不要输出 JSON,只输出转写文本;
- 图片中没有可读文本时输出空行。"""

# 补看轮(诊断取证:约半数漏抽是首轮转写整块丢失——密集勾选框组、
# 多列表格整行、印章/签名区)。只输出缺失文字,行级去重后并入底稿。
VISION_SUPPLEMENT_SYSTEM = """你是文档转写校对器。给你一张图片和它已有的转写稿。
请再次仔细查看图片,只输出图片中存在、但转写稿中缺失的文字:
- 每行一条,保持原文写法,不要解释、不要重复转写稿已有的内容;
- 特别注意表格边角、勾选框组、密集小字、多列并排区域、印章与签名;
- 转写稿已完整覆盖图片时,只输出:无缺失。"""

_SUPPLEMENT_EMPTY_MARKER = "无缺失"
_SUPPLEMENT_MARKER_LINE = "--- 补充转写 ---"


def _norm_for_dedup(text: str) -> str:
    return "".join(ch for ch in text.casefold() if not ch.isspace())


def _filter_supplement_lines(first_pass: str, supplement: str) -> list[str] | None:
    """补看轮输出行级去重(已在首轮底稿中的行丢弃);疑似幻觉复读返回 None。

    护栏:去重后的新增文字量超过 max(400, 2×首轮长度) 视为幻觉复读,
    整批丢弃(补看只该补缺角,不该比首轮还长)。
    """
    supplement = supplement.strip()
    if not supplement or _SUPPLEMENT_EMPTY_MARKER in supplement:
        return []
    first_norm = _norm_for_dedup(first_pass)
    fresh: list[str] = []
    for raw_line in supplement.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        norm = _norm_for_dedup(line)
        if norm and norm not in first_norm:
            fresh.append(line)
    if sum(len(line) for line in fresh) > max(400, 2 * len(first_pass)):
        return None
    return fresh

# 类别引导对齐 db_core.PROFILE_TEMPLATES;未知类别由解析器/upsert 护栏归入 general_facts。
# 输出用管道行而非 JSON:7B 模型对中英混排密集文本的 JSON 生成不稳定(dev 实证)。
DOC_FACTS_SYSTEM = """你是企业文档事实抽取器。输入是一份文档的逐字转写稿。
每找到一条事实,就输出一行,格式(用竖线分隔的四段):
category | key | value | evidence

- category 取以下之一:user_preferences、people_relations、project_status、finance_budget、location_events、general_facts
- key 用 snake_case 唯一键;value 是事实当前值;evidence 是支撑该事实的转写稿原文片段
- 除了事实行,不要输出任何其他文字;没有事实就只输出一行:无事实

抽取规则:
- 系统性抽取全部具体业务事实;单据/票据类文本中,以下要素只要出现就必须逐项抽取:
  商家或主体名称、完整地址、日期、单据编号、各项金额与税额、负责人/联系人、条款比例、期限;
- 登记表/申请表/简历类表单的填写项同样是事实:姓名、出生年月、学历、专业、工作单位、
  职位、联系方式、账号、证照编号、机关名称等,逐项抽取;
- value 必须逐字取自原文,严禁改写格式(原文 12/28/2017 就写 12/28/2017,不得改成 2017-12-28);
- 名称与地址等要素常跨多行排版:主体/商家名称须合并相邻行取完整名称(含字号、品牌前缀与公司后缀);地址须把门牌、街道、区镇、邮编、城市各行合并为一个完整值;
- 表单勾选/选项组(如 √甲 □乙、1.甲√ 2.乙):value 保留整组选项的原文枚举(含序号与勾选符号),不要只保留被选中项,也不要清洗改写;
- 同类要素属于多个单据/实体时,key 加实体标识区分(如 order_total_po8015),绝不复用同一个 key;
- 只抽取转写稿中明确出现的内容,严禁推测或补全;
- 口号、标语、栏目标题、装饰文字不是业务事实,不要抽取;装饰页输出:无事实"""


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
        retry_warnings: list[str] = []
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

            def _transcribe(msg: dict[str, Any] = message) -> dict[str, Any]:
                reply: dict[str, Any] = self.model_interface.chat(
                    "vision",
                    messages=[msg],
                    mode=self.mode,
                    override_system_prompt=VISION_TRANSCRIBE_SYSTEM,
                )
                return reply

            response = call_with_transient_retry(_transcribe, warnings=retry_warnings)
            vlm_model = str(response.get("model") or vlm_model)
            page_text = str((response.get("message") or {}).get("content") or "").strip()

            # 补看轮:首轮有文字才补(空白页不补,防诱导幻觉);只并入缺失行。
            if page_text:
                supplement_prompt = (
                    f"来源: {asset.source_uri or asset.sha256[:12]}"
                    f" 第 {page.index + 1}/{asset.page_count} 页。已有转写稿:\n{page_text}\n\n"
                    "请按系统提示只输出图片中缺失的文字。"
                )
                supplement_message = build_image_message(provider, supplement_prompt, page)

                def _supplement(msg: dict[str, Any] = supplement_message) -> dict[str, Any]:
                    reply: dict[str, Any] = self.model_interface.chat(
                        "vision",
                        messages=[msg],
                        mode=self.mode,
                        override_system_prompt=VISION_SUPPLEMENT_SYSTEM,
                    )
                    return reply

                supplement_reply = call_with_transient_retry(
                    _supplement, warnings=retry_warnings)
                supplement_raw = str(
                    (supplement_reply.get("message") or {}).get("content") or "")
                fresh_lines = _filter_supplement_lines(page_text, supplement_raw)
                if fresh_lines is None:
                    retry_warnings.append("vision_supplement_dropped: too_long")
                elif fresh_lines:
                    retry_warnings.append(f"vision_supplement_added: {len(fresh_lines)}")
                    page_text = "\n".join(
                        [page_text, _SUPPLEMENT_MARKER_LINE, *fresh_lines])

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
            # dev 取证:漏抽 92% 是"底稿已有但单次生成没枚举到"——文档面开补抽。
            completeness_pass=True,
        )

        # 确定性兜底:半结构化 键:值 行解析,与 LLM 结果取并集(补单次枚举遗漏)。
        # 规则值逐字来自底稿;装饰页无冒号结构 → 零产出,不影响 halluc_ok。
        kv_facts = parse_kv_lines(full_text)
        facts = union_kv_facts(facts, kv_facts)

        # 版面结构兜底(表格行/问答行/宽空格对/序号选项组):单向超集并集——
        # 打包值常是现有值的超集且携带同行新信息,只有"已被覆盖"才不存。
        structure_facts = parse_structure_facts(full_text)
        facts = union_superset_facts(facts, structure_facts)

        return ExtractionResult(
            full_text=full_text,
            candidate_facts=tuple(facts),
            extractor_name=self.name,
            model_name=f"{vlm_model}+{llm_model}",
            extractor_version=self.version,
            warnings=tuple(retry_warnings + warnings),
        )
