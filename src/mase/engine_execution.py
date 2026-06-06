"""执行阶段 mixin：把 planner、reasoning workspace 与 executor 调用隔离出来。

依赖方向上，本模块只消费 `mode_selector`、答案归一化、router 常量和
`ModelInterface` 能力，不持有检索或持久化细节。这样 `engine.MASESystem`
可以专注编排顺序，而执行阶段的协作策略能独立演进和测试。
"""
from __future__ import annotations

import os
from typing import Any

from .answer_normalization import (
    candidate_names_from_fact_sheet,
    extract_answer,
    extract_fact_sheet_list_lookup_answer,
    extract_fact_sheet_shift_lookup_answer,
    extract_numbered_list_item,
    extract_ordinal_index_from_question,
    normalize_compact_lookup_answer,
    normalize_other_options_answer,
    normalize_preference_profile_answer,
    normalize_three_event_order_answer,
)
from .mode_selector import (
    generalizer_mode_for_question,
    is_long_memory,
    lme_qtype_routing_enabled,
    lme_question_type,
    local_only_models_enabled,
    select_executor_mode,
    verify_mode_for_question,
)
from .models import PlannerSnapshot
from .reasoning_engine import build_reasoning_workspace
from .router import ROUTER_SYSTEM
from .topic_threads import detect_text_language


class EngineExecutionMixin:
    """执行器相关能力集合，由 `MASESystem` 继承后调用。

    这里的 public-ish 方法保持兼容旧测试和脚本；真实职责是构造 executor
    prompt、选择 verify/split 协作模式，并把模型输出归一化成最终答案。
    """

    model_interface: Any
    planner_agent: Any
    router_agent: Any

    @staticmethod
    def _executor_prompt(
        user_question: str,
        fact_sheet: str,
        instruction_package: str = "",
        draft_answer: str = "",
    ) -> str:
        """构造 executor 输入，并按用户问题语言切换中英文模板。"""
        question_reference_time = str(os.environ.get("MASE_QUESTION_REFERENCE_TIME") or "").strip()
        if detect_text_language(user_question) == "en":
            parts = [f"Fact sheet:\n{fact_sheet}"]
            if question_reference_time:
                parts.append(f"QUESTION_DATE:\n{question_reference_time}")
            if instruction_package.strip():
                parts.append(f"Instruction package:\n{instruction_package}")
            if draft_answer.strip():
                parts.append(f"Draft answer:\n{draft_answer}")
            parts.append(f"Question:\n{user_question}")
            return "\n\n".join(parts)
        parts = [f"事实备忘录：\n{fact_sheet}"]
        if question_reference_time:
            parts.append(f"QUESTION_DATE:\n{question_reference_time}")
        if instruction_package.strip():
            parts.append(f"指令包：\n{instruction_package}")
        if draft_answer.strip():
            parts.append(f"回答草稿：\n{draft_answer}")
        parts.append(f"用户问题：\n{user_question}")
        return "\n\n".join(parts)

    @staticmethod
    def _candidate_names_from_fact_sheet(fact_sheet: str) -> list[str]:
        return candidate_names_from_fact_sheet(fact_sheet)

    @classmethod
    def _extract_answer(cls, mode: str, content: str, user_question: str, fact_sheet: str = "") -> str:
        return extract_answer(mode, content, user_question, fact_sheet)

    @staticmethod
    def _normalize_three_event_order_answer(content: str, user_question: str) -> str:
        return normalize_three_event_order_answer(content, user_question)

    @staticmethod
    def _normalize_preference_profile_answer(content: str) -> str:
        return normalize_preference_profile_answer(content)

    @classmethod
    def _normalize_other_options_answer(cls, content: str, user_question: str) -> str:
        return normalize_other_options_answer(content, user_question)

    @staticmethod
    def _normalize_compact_lookup_answer(content: str, user_question: str) -> str:
        return normalize_compact_lookup_answer(content, user_question)

    @staticmethod
    def _extract_ordinal_index_from_question(user_question: str) -> int:
        return extract_ordinal_index_from_question(user_question)

    @staticmethod
    def _extract_numbered_list_item(text: str, target_index: int) -> str:
        return extract_numbered_list_item(text, target_index)

    @classmethod
    def _extract_fact_sheet_list_lookup_answer(cls, user_question: str, fact_sheet: str) -> str:
        return extract_fact_sheet_list_lookup_answer(user_question, fact_sheet)

    @staticmethod
    def _extract_fact_sheet_shift_lookup_answer(user_question: str, fact_sheet: str) -> str:
        return extract_fact_sheet_shift_lookup_answer(user_question, fact_sheet)

    @staticmethod
    def _should_use_planner(route_action: str, executor_mode: str, fact_sheet: str) -> bool:
        """判断是否值得走模型 planner。

        没有记忆证据时直接用启发式计划，避免 planner 在空事实表上制造伪步骤；
        grounded_* 模式则保留 planner，因为后续回答要解释事实比较/聚合过程。
        """
        normalized_fact_sheet = fact_sheet.strip()
        if route_action == "search_memory":
            return True
        if not normalized_fact_sheet or normalized_fact_sheet == "无相关记忆。":
            return False
        return executor_mode.startswith(("grounded_analysis", "grounded_disambiguation"))

    @staticmethod
    def _heuristic_plan(executor_mode: str, user_question: str, fact_sheet: str) -> PlannerSnapshot:
        """无额外 LLM 调用的保守计划，用于确定性 benchmark 和低证据路径。"""
        language = detect_text_language(user_question)
        has_memory = bool(fact_sheet.strip()) and fact_sheet.strip() != "无相关记忆。"
        if language == "en":
            if executor_mode.startswith("grounded_analysis"):
                text = "Plan: extract the relevant facts, compute the answer from the fact sheet, and return only the supported result."
            elif executor_mode.startswith("grounded_disambiguation"):
                text = "Plan: compare the candidate facts in memory, discard distractors, and answer with the best-supported match."
            elif has_memory:
                text = "Plan: answer directly from the retrieved fact sheet without adding outside knowledge."
            else:
                text = "Plan: answer directly with the available information."
        else:
            if executor_mode.startswith("grounded_analysis"):
                text = "Plan: 抽取相关事实，基于事实备忘录完成计数/比较/聚合，再输出最终答案。"
            elif executor_mode.startswith("grounded_disambiguation"):
                text = "Plan: 对比候选事实，排除混淆项，仅依据最匹配的记录作答。"
            elif has_memory:
                text = "Plan: 直接依据已检索到的事实备忘录回答，不补充外部知识。"
            else:
                text = "Plan: 直接根据当前可用信息回答。"
        return PlannerSnapshot(text=text, source="heuristic")

    def _build_planner_snapshot(
        self,
        route_action: str,
        executor_mode: str,
        user_question: str,
        fact_sheet: str,
    ) -> PlannerSnapshot:
        """返回 planner 快照，优先保证“有证据才规划”的边界。"""
        if not self._should_use_planner(route_action, executor_mode, fact_sheet):
            return self._heuristic_plan(executor_mode, user_question, fact_sheet)
        return PlannerSnapshot(
            text=self.planner_agent.plan(query=user_question, memory_context=fact_sheet, mode="task_planning"),
            source="model",
        )

    def _select_collaboration_mode(self, user_question: str, fact_sheet: str, executor_mode: str) -> str:
        """选择 executor 后处理策略：off / verify / split。

        配置显式指定时优先；否则根据事实表证据、LongMemEval 问题类型和
        reasoning workspace 的风险判断决定是否增加 verifier/generalizer hop。
        """
        routing_config = self.model_interface.get_agent_config("executor").get("routing") or {}
        configured = str(routing_config.get("default_collaboration_mode") or "off").strip().lower()
        if configured in {"verify", "split"}:
            return configured
        if not fact_sheet.strip() or fact_sheet.strip() == "无相关记忆。":
            return "off"
        if is_long_memory() and lme_qtype_routing_enabled() and lme_question_type() in {"single-session-preference", "multi-session"}:
            return "split"
        workspace = build_reasoning_workspace(user_question, fact_sheet)
        if workspace.verifier_action == "verify":
            return "verify"
        if executor_mode.startswith(("grounded_analysis", "grounded_disambiguation")):
            return "verify"
        return "off"

    def _build_instruction_package(self, user_question: str, fact_sheet: str, planner: PlannerSnapshot) -> str:
        """合并 planner 与 reasoning workspace，形成 executor 可读的额外指令包。"""
        workspace = build_reasoning_workspace(user_question, fact_sheet)
        parts = [f"Planner:\n{planner.text}", workspace.to_text()]
        return "\n\n".join(part for part in parts if part.strip())

    def describe_executor_target(
        self,
        mode: str,
        user_question: str,
        use_memory: bool,
        memory_heat: str | None = None,
        executor_role: str | None = None,
    ) -> dict[str, Any]:
        """生成 trace/观测用的 executor 目标信息，不参与模型请求体。"""
        target = self.model_interface.describe_agent("executor", mode=mode)
        target.update(
            {
                "mode": mode,
                "use_memory": use_memory,
                "memory_heat": memory_heat,
                "executor_role": executor_role or ("memory" if use_memory else "general"),
                "question_language": detect_text_language(user_question),
            }
        )
        return target

    def call_router(
        self,
        user_question: str,
        system_prompt: str = ROUTER_SYSTEM,
        apply_heuristic: bool = True,
    ) -> dict[str, Any]:
        del apply_heuristic
        return self.router_agent.decide(user_question=user_question, system_prompt=system_prompt)

    def probe_router(
        self,
        user_question: str,
        system_prompt: str = ROUTER_SYSTEM,
        apply_heuristic: bool = False,
    ) -> dict[str, Any]:
        del apply_heuristic
        return self.router_agent.decide(user_question=user_question, system_prompt=system_prompt)

    def call_executor(
        self,
        user_question: str,
        fact_sheet: str,
        allow_general_knowledge: bool = False,
        task_type: str | None = None,
        use_memory: bool | None = None,
        memory_heat: str | None = None,
        executor_role: str | None = None,
        collaboration_mode: str | None = None,
        instruction_package: str = "",
    ) -> str:
        """调用 executor 并按协作策略返回最终答案。

        主调用先得到 draft answer；`verify` 再走校验模式，`split` 再走泛化/汇总
        模式。每条路径最后都回到同一套答案抽取函数，避免不同模式输出格式漂移。
        """
        del allow_general_knowledge, task_type, use_memory, memory_heat, executor_role
        mode = select_executor_mode(user_question, fact_sheet)
        effective_collaboration = collaboration_mode or self._select_collaboration_mode(user_question, fact_sheet, mode)
        prompt = self._executor_prompt(user_question, fact_sheet, instruction_package=instruction_package)
        try:
            response = self.model_interface.chat(
                "executor",
                messages=[{"role": "user", "content": prompt}],
                mode=mode,
            )
        except Exception as error:
            error_text = str(error).lower()
            local_temporal_deepreason = (
                is_long_memory()
                and local_only_models_enabled()
                and lme_question_type() == "temporal-reasoning"
                and mode in {"grounded_long_memory_deepreason_english", "grounded_long_memory_deepreason"}
            )
            runner_terminated = (
                "llama runner process has terminated" in error_text
                or ("status code: 500" in error_text and "responseerror" in error_text)
            )
            if not (local_temporal_deepreason and runner_terminated):
                raise
            # 本地小模型 deepreason 路径偶发 runner 崩溃时，降级到普通长记忆模式；
            # 只覆盖已知的 LongMemEval temporal 场景，避免吞掉真实 provider 错误。
            mode = "grounded_long_memory_english" if detect_text_language(user_question) == "en" else "grounded_long_memory"
            response = self.model_interface.chat(
                "executor",
                messages=[{"role": "user", "content": prompt}],
                mode=mode,
            )
        content = str((response.get("message") or {}).get("content") or "")
        draft_answer = self._extract_answer(mode, content, user_question, fact_sheet)
        if effective_collaboration == "verify":
            # verifier 只复核 draft，不重新选择检索证据；这样回答仍可追溯到同一张
            # fact sheet。
            verify_mode = verify_mode_for_question(user_question)
            verify_response = self.model_interface.chat(
                "executor",
                messages=[
                    {
                        "role": "user",
                        "content": self._executor_prompt(
                            user_question,
                            fact_sheet,
                            instruction_package=instruction_package,
                            draft_answer=draft_answer,
                        ),
                    }
                ],
                mode=verify_mode,
            )
            verified_content = str((verify_response.get("message") or {}).get("content") or "").strip()
            final_ans = self._extract_answer(verify_mode, verified_content or draft_answer, user_question, fact_sheet)
            return final_ans
        if effective_collaboration == "split":
            # split 让 generalizer 在 draft 基础上整理表达，主要服务多会话偏好题；
            # 最终仍走 _extract_answer 收敛为可评分答案。
            generalizer_mode = generalizer_mode_for_question(user_question)
            final_response = self.model_interface.chat(
                "executor",
                messages=[
                    {
                        "role": "user",
                        "content": self._executor_prompt(
                            user_question,
                            fact_sheet,
                            instruction_package=instruction_package,
                            draft_answer=draft_answer,
                        ),
                    }
                ],
                mode=generalizer_mode,
            )
            final_content = str((final_response.get("message") or {}).get("content") or "").strip()
            return self._extract_answer(generalizer_mode, final_content or draft_answer, user_question, fact_sheet)
        return draft_answer

    def summarize_interaction(self, user_question: str, assistant_response: str) -> str:
        combined = " ".join(part.strip() for part in [user_question, assistant_response] if str(part).strip())
        return combined[:48]
