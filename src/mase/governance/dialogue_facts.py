"""对话事实 LLM 抽取器(投影切片③,设计 2026-07-08 §4.5)。

契约经 knowledge-update 78 例四轮 A/B 验证(judge 53.8→74.4):全量抽取
user 陈述的个人事实、同主题复用同 key(supersede 成链)、value 逐字取自
原文(抗幻觉红线,治理层 span 定位天然强制)。抽取模型走 config 的
``dialogue_facts`` agent,缺省回落 ``doc_facts``(先例:多模态文档抽取)。
"""
from __future__ import annotations

from typing import Any

DIALOGUE_FACTS_SYSTEM = """You extract personal facts from one chat message by a user.
Output one line per fact, pipe-delimited four fields:
category | key | value | evidence

- category: one of user_preferences, people_relations, project_status, finance_budget, location_events, general_facts
- key: snake_case, stable across messages about the SAME topic (so a later value about the
  same thing reuses the same key and can supersede the earlier one). E.g. running_5k_best_time,
  bikes_owned_count, gym_days.
- value: the current stated value, copied verbatim from the message
- evidence: the exact substring of the message that states it

Rules:
- Extract EVERY concrete personal fact the user states: counts, times, dates, amounts, places,
  preferences, statuses, records, goals-that-became-values. Do NOT filter to only the salient one.
- If the message states a NUMBER or MEASUREMENT about the user (a best time, a count, an amount,
  a date), you MUST extract it — these are exactly the update-tracked facts.
- Copy values verbatim (27:12 stays 27:12; four stays four).
- Only facts explicitly in THIS message. No inference, no outside knowledge.
- Assistant paraphrases are not the source; extract the user's own statements.
- If the message states no personal fact, output exactly: 无事实"""


def extract_dialogue_facts(model_interface: Any, content: str) -> list[Any]:
    """对单条 user 事件内容跑 LLM 抽取;返回 CandidateFact 列表。

    复用 ``text_facts.extract_facts_from_text``(畸形回复降级零事实、
    completeness_pass 补抽长消息漏抽——POC 实测显著性过滤是漏抽主因)。
    agent 解析顺序:``dialogue_facts`` → 回落 ``doc_facts``。
    """
    from mase.multimodal.text_facts import extract_facts_from_text

    agent_type = "dialogue_facts"
    try:
        if not (model_interface.get_agent_config(agent_type) or {}).get("model_name"):
            agent_type = "doc_facts"
    except Exception:  # noqa: BLE001 - agent 探测失败回落先例配置
        agent_type = "doc_facts"
    facts, _warnings, _model = extract_facts_from_text(
        model_interface,
        agent_type=agent_type,
        system_prompt=DIALOGUE_FACTS_SYSTEM,
        text=content,
        completeness_pass=True,
    )
    return facts


__all__ = ["DIALOGUE_FACTS_SYSTEM", "extract_dialogue_facts"]
