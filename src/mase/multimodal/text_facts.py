"""从既定文本抽取事实的公共第二段(视觉/音频两段式共用)。

两段式白盒契约:第一段产出忠实转写(审计底稿),本模块负责第二段——
把底稿交给本地文本 LLM 抽取"既定事实"。抽取只能基于底稿原文
(evidence 引用),不允许推测;这是"在既定事实的基础上保证正确率和
低幻觉率"哲学的执行点。

输出契约(P6):管道行格式 ``category | key | value | evidence``,
每行一条;无事实输出 ``无事实``。dev 实证 7B 模型对中英混排密集表单
的 JSON 生成 7/10 崩溃且重试无效,行格式稳定得多,且比 JSON 更人眼
可读;旧 JSON 回复仍兼容解析(迁移期零破坏)。
"""
from __future__ import annotations

from typing import Any

from .extractor import CandidateFact, coerce_confidence, parse_json_blob

TEXT_FACTS_CHUNK_CHARS = 6000  # 超过则按行边界分块(不劈行)

EMPTY_MARKERS = ("无事实", "NO_FACTS")
_VALID_CATEGORIES_HINT = {"user_preferences", "people_relations", "project_status",
                          "finance_budget", "location_events", "general_facts"}


def parse_fact_lines(raw: str) -> list[CandidateFact] | None:
    """解析管道行格式;兼容旧 JSON;完全不可解析返回 None(触发重试)。

    行规则:按 ``|`` 切成 ≥4 段取前 4 段(category/key/value/evidence),
    category 非枚举时按 upsert 护栏习惯落 general_facts;非管道行忽略
    (模型偶发的前后缀说明不致命)。显式空标记(无事实/NO_FACTS)返回 []。
    """
    text = raw.strip()
    if not text:
        return None
    json_reply = parse_json_blob(text)
    if json_reply is not None and isinstance(json_reply.get("facts"), list):
        facts_json: list[CandidateFact] = []
        for item in json_reply["facts"]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            value = str(item.get("value") or "").strip()
            if key and value:
                facts_json.append(CandidateFact(
                    category=str(item.get("category") or "general_facts"),
                    key=key, value=value,
                    confidence=coerce_confidence(item.get("confidence")),
                    evidence=str(item.get("evidence") or "").strip(),
                ))
        return facts_json

    facts: list[CandidateFact] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4:
            continue
        category, key, value = parts[0], parts[1], parts[2]
        evidence = " | ".join(parts[3:]).strip()
        if not key or not value or " " in key.replace("_", ""):
            continue
        if category not in _VALID_CATEGORIES_HINT:
            category = "general_facts"
        facts.append(CandidateFact(
            category=category, key=key, value=value,
            confidence=0.8,  # 行格式不带自评分;固定尽力值,含义见 CandidateFact 注释
            evidence=evidence,
        ))
    if facts:
        return facts
    if any(marker in text for marker in EMPTY_MARKERS):
        return []
    return None


def chunk_lines(text: str, chunk_chars: int) -> list[str]:
    """按行边界切块:不劈开单行,块字符数 ≤ chunk_chars(单行超限自成一块)。"""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        if current and current_len + len(line) + 1 > chunk_chars:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def extract_facts_from_text(
    model_interface: Any,
    *,
    agent_type: str,
    system_prompt: str,
    text: str,
    chunk_chars: int | None = None,
) -> tuple[list[CandidateFact], list[str], str]:
    """对底稿全文逐块调用文本 LLM 抽事实;返回 (facts, warnings, llm_model)。

    畸形回复降级为该块无事实 + warning,绝不抛穿(底稿已入库可召回,
    事实缺失可重跑,这是两段式的容错红利)。chunk_chars=None 时取模块
    默认(调用方可传自己的常量,如音频侧的 TRANSCRIPT_CHUNK_CHARS)。
    """
    facts: list[CandidateFact] = []
    warnings: list[str] = []
    llm_model = "unknown"
    chunks = chunk_lines(text, chunk_chars if chunk_chars is not None else TEXT_FACTS_CHUNK_CHARS)
    if len(chunks) > 1:
        warnings.append(f"chunked: {len(chunks)} parts")

    for chunk_text in chunks:
        parsed: list[CandidateFact] | None = None
        for attempt in (1, 2):
            # 重试必须改变输入:temp=0 下同输入只会复现同样的坏输出。
            content = chunk_text if attempt == 1 else (
                chunk_text
                + "\n\n(你上一次的输出无法解析。请严格按每行一条"
                  " `category | key | value | evidence` 的格式输出;没有事实就只输出 `无事实`。)"
            )
            response = model_interface.chat(
                agent_type,
                messages=[{"role": "user", "content": content}],
                override_system_prompt=system_prompt,
            )
            llm_model = str(response.get("model") or llm_model)
            raw = str((response.get("message") or {}).get("content") or "")
            parsed = parse_fact_lines(raw)
            if parsed is not None:
                if attempt == 2:
                    warnings.append("unparseable_response(recovered_on_retry)")
                break
        if parsed is None:
            warnings.append("unparseable_response")
            continue
        facts.extend(parsed)
    return facts, warnings, llm_model
