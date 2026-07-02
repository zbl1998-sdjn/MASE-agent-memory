"""从既定文本抽取事实的公共第二段(视觉/音频两段式共用)。

两段式白盒契约:第一段产出忠实转写(审计底稿),本模块负责第二段——
把底稿交给本地文本 LLM,按严格 JSON 契约抽取"既定事实"。抽取只能
基于底稿原文(evidence 引用),不允许推测;这是"在既定事实的基础上
保证正确率和低幻觉率"哲学的执行点。
"""
from __future__ import annotations

from typing import Any

from .extractor import CandidateFact, coerce_confidence, parse_json_blob

TEXT_FACTS_CHUNK_CHARS = 6000  # 超过则按行边界分块(不劈行)


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
        reply = None
        for attempt in (1, 2):
            # 重试必须改变输入:temp=0 下同输入只会复现同样的坏输出。
            content = chunk_text if attempt == 1 else (
                chunk_text + "\n\n(你上一次的输出不是合法 JSON。请只输出符合契约的 JSON 对象,不要任何其他文字。)"
            )
            response = model_interface.chat(
                agent_type,
                messages=[{"role": "user", "content": content}],
                override_system_prompt=system_prompt,
            )
            llm_model = str(response.get("model") or llm_model)
            raw = str((response.get("message") or {}).get("content") or "")
            reply = parse_json_blob(raw)
            if reply is not None:
                if attempt == 2:
                    warnings.append("non_json_response(recovered_on_retry)")
                break
        if reply is None:
            warnings.append("non_json_response")
            continue
        for item in reply.get("facts") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            value = str(item.get("value") or "").strip()
            if not key or not value:
                continue
            facts.append(
                CandidateFact(
                    category=str(item.get("category") or "general_facts"),
                    key=key,
                    value=value,
                    confidence=coerce_confidence(item.get("confidence")),
                    evidence=str(item.get("evidence") or "").strip(),
                )
            )
    return facts, warnings, llm_model
