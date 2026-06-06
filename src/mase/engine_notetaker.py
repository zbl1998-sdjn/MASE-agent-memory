"""notetaker 阶段 mixin：把检索命中压缩成 executor 可消费的 fact sheet。

本模块不负责搜索本身，只负责把 `notetaker_agent.search()` 的结果整理成
可控证据包，并决定是否使用确定性事实表或模型压缩事实表。
"""
from __future__ import annotations

from typing import Any

from .fact_sheet import build_long_context_fact_sheet
from .mode_selector import (
    is_long_memory,
    is_multidoc_long_context,
    select_notetaker_mode,
    use_deterministic_fact_sheet,
)
from .topic_threads import detect_text_language


class EngineNotetakerMixin:
    """事实表构建相关能力，由 `MASESystem` 在检索完成后调用。"""

    notetaker_agent: Any
    model_interface: Any

    def _format_search_results_for_notetaker(self, results: list[dict[str, Any]]) -> str:
        """把检索行展开成带来源/新鲜度/冲突状态的纯文本证据列表。"""
        lines: list[str] = []
        for index, item in enumerate(results, start=1):
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            summary = str(item.get("summary") or "").strip()
            thread_label = str(item.get("thread_label") or "").strip()
            parts = [f"[{index}] {content}"]
            for key in ("_source", "retrieval_reason", "freshness", "conflict_status", "source_reason"):
                value = str(item.get(key) or "").strip()
                if value:
                    parts.append(f"{key.lstrip('_')}={value}")
            if item.get("history_depth"):
                parts.append(f"history_depth={item['history_depth']}")
            for key in ("updated_at", "superseded_at"):
                value = str(item.get(key) or "").strip()
                if value:
                    parts.append(f"{key}={value}")
            if summary:
                parts.append(f"summary={summary}")
            if thread_label:
                parts.append(f"thread={thread_label}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    def _build_fact_sheet_with_notetaker(
        self,
        user_question: str,
        search_results: list[dict[str, Any]],
        memory_heat: str,
    ) -> tuple[str, str]:
        """根据运行模式生成 fact sheet，并返回实际使用的 notetaker 模式。

        空检索直接返回拒猜提示；确定性模式绕过 LLM 压缩，普通模式才让
        notetaker 模型做最小充分事实表。
        """
        raw_fact_sheet = self.notetaker_agent.build_fact_sheet(search_results, question=user_question)
        if not search_results:
            return "未找到相关记忆证据；不要猜测具体值。", "none"
        if use_deterministic_fact_sheet():
            # benchmark / 长上下文对照需要稳定输入，直接由结构化规则生成事实表。
            return (
                build_long_context_fact_sheet(
                    user_question,
                    search_results,
                    notetaker=self.notetaker_agent,
                    multidoc=is_multidoc_long_context(),
                    long_memory=is_long_memory(),
                ),
                "long_context_raw",
            )
        mode = select_notetaker_mode(user_question=user_question, memory_heat=memory_heat)
        if detect_text_language(user_question) == "en":
            # 英文问题保持英文 fact-card 约束，减少小模型跨语言改写实体的风险。
            system_prompt = (
                "You are MASE's notetaker fact-card agent. Compress retrieved memory into a strict fact sheet.\n"
                "Rules:\n"
                "1. Use only the retrieved records.\n"
                "2. Keep exact entities, numbers, dates, and actions.\n"
                "3. Remove duplicates and irrelevant details.\n"
                "4. For counting/comparison questions, list atomic facts separately.\n"
                "5. End with exactly two metadata lines: evidence_confidence=<high|medium|low> and verifier_action=<answer|verify|refuse>.\n"
                "Return plain text only."
            )
            prompt = (
                f"Question:\n{user_question}\n\n"
                f"Retrieved records:\n{self._format_search_results_for_notetaker(search_results)}\n\n"
                "Write the minimal fact sheet."
            )
        else:
            # 中文问题使用中文约束，要求保留实体、数字、日期、动作原词，避免压缩
            # 阶段把可评分答案改写掉。
            system_prompt = (
                "你是 MASE 的记事压缩智能体。请把检索出的候选记录压缩成严格 fact sheet。\n"
                "规则：\n"
                "1. 只能使用候选记录里的内容。\n"
                "2. 保留实体、数字、日期、动作原词。\n"
                "3. 删除重复与无关信息。\n"
                "4. 若问题涉及计数/比较/聚合，必须把原子事实逐条列出。\n"
                "5. 最后必须追加两行：evidence_confidence=<high|medium|low> 与 verifier_action=<answer|verify|refuse>。\n"
                "只输出纯文本 fact sheet。"
            )
            prompt = (
                f"用户问题：\n{user_question}\n\n"
                f"候选记录：\n{self._format_search_results_for_notetaker(search_results)}\n\n"
                "请输出最小充分事实备忘录。"
            )
        response = self.model_interface.chat(
            "notetaker",
            messages=[{"role": "user", "content": prompt}],
            mode=mode,
            override_system_prompt=system_prompt,
        )
        fact_sheet = str((response.get("message") or {}).get("content") or "").strip()
        return (fact_sheet or raw_fact_sheet), mode
