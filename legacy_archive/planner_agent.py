from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from model_interface import ModelInterface


@dataclass(frozen=True)
class PlannerModelPlan:
    task_description: str
    query_variants: list[str]
    topic_hints: list[str]
    recent_count: int
    expected_output_format: str
    reasoning_hint: str
    sub_tasks: list[str]
    verification_focus: list[str]
    scope_filters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_description": self.task_description,
            "query_variants": list(self.query_variants),
            "topic_hints": list(self.topic_hints),
            "recent_count": self.recent_count,
            "expected_output_format": self.expected_output_format,
            "reasoning_hint": self.reasoning_hint,
            "sub_tasks": list(self.sub_tasks),
            "verification_focus": list(self.verification_focus),
            "scope_filters": dict(self.scope_filters),
        }


@dataclass(frozen=True)
class InstructionPackage:
    task_description: str
    fact_sheet: str
    expected_output_format: str
    reasoning_hint: str
    background_summary: str
    sub_tasks: list[str]
    verification_focus: list[str]
    scope_filters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_description": self.task_description,
            "fact_sheet": self.fact_sheet,
            "expected_output_format": self.expected_output_format,
            "reasoning_hint": self.reasoning_hint,
            "background_summary": self.background_summary,
            "sub_tasks": list(self.sub_tasks),
            "verification_focus": list(self.verification_focus),
            "scope_filters": dict(self.scope_filters),
        }

    def to_prompt(self) -> str:
        lines = ["执行指令包：", f"任务描述：{self.task_description}"]
        if self.background_summary.strip():
            lines.append(f"会话背景：{self.background_summary}")
        if self.sub_tasks:
            lines.append("执行子任务：" + " -> ".join(self.sub_tasks))
        if self.reasoning_hint.strip():
            lines.append(f"推理提示：{self.reasoning_hint}")
        if self.verification_focus:
            lines.append("验证焦点：" + " | ".join(self.verification_focus))
        if self.scope_filters:
            lines.append(f"时空约束：{json.dumps(self.scope_filters, ensure_ascii=False, sort_keys=True)}")
        if self.expected_output_format.strip():
            lines.append(f"输出格式：{self.expected_output_format}")
        lines.append("事实备忘录：")
        lines.append(self.fact_sheet or "(空)")
        return "\n".join(lines)


class PlannerAgent:
    def __init__(self, model_interface: ModelInterface | None = None) -> None:
        self.model_interface = model_interface
        self.session_summary = ""

    def get_session_summary(self) -> str:
        return self.session_summary

    def _dedupe_strings(self, items: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = str(item or "").strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(normalized)
        return result

    def _scope_filter_values(self, filters: dict[str, Any] | None, key: str) -> list[str]:
        if not isinstance(filters, dict):
            return []
        raw_values = filters.get(key)
        if raw_values is None:
            return []
        if isinstance(raw_values, list):
            return [str(item) for item in raw_values]
        return [str(raw_values)]

    def _parse_json_object(self, content: str) -> dict[str, Any] | None:
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None

    def _is_usable_summary(self, summary: str) -> bool:
        normalized = summary.strip()
        if len(normalized) < 8:
            return False
        if len(re.findall(r"[A-Za-z\u4e00-\u9fff0-9]", normalized)) < 6:
            return False
        return True

    def _default_output_format(self, task_type: str) -> str:
        if task_type == "code_generation":
            return "直接输出可运行代码；必要时附一行简短说明。"
        if task_type == "math_compute":
            return "先给结果，再给最短必要过程。"
        if task_type == "structured_task":
            return "严格按用户要求的结构输出。"
        return "直接回答问题；若证据不足，明确拒答。"

    def _default_reasoning_hint(self, user_question: str, planner_strategy: str) -> str:
        lowered = user_question.lower()
        if any(marker in lowered for marker in ("autonomous decision", "decision chain", "source arbitration", "evidence chain")):
            return "优先沿着证据链做源裁决，只保留直接支持的事实，不要补链推断。"
        if "是谁" in user_question or "叫什么" in user_question or "which" in lowered or "who" in lowered:
            return "注意区分相似实体，逐条排除不匹配候选。"
        if any(marker in lowered for marker in ("how many", "how much", "how long", "总共", "合计", "一共")):
            return "先提取原子事实，再做确定性计数或求和。"
        if planner_strategy == "query_rewrite_lookup":
            return "优先利用改写后的检索表达，避免泛化回答。"
        return ""

    def _default_sub_tasks(self, task_type: str, user_question: str) -> list[str]:
        lowered = user_question.lower()
        if any(marker in lowered for marker in ("autonomous decision", "decision chain", "source arbitration", "evidence chain")):
            return ["retrieve evidence", "arbitrate sources", "verify chain", "final answer"]
        if task_type == "grounded_analysis":
            if any(marker in lowered for marker in ("how many", "how much", "how long", "difference", "compare", "total")):
                return ["retrieve evidence", "verify coverage", "deterministic reasoning", "final answer"]
            return ["retrieve evidence", "analyze facts", "final answer"]
        if task_type == "grounded_answer":
            return ["retrieve evidence", "verify support", "final answer"]
        if task_type == "grounded_disambiguation":
            return ["retrieve candidates", "compare supports", "final answer"]
        return ["understand task", "final answer"]

    def _default_verification_focus(self, task_type: str, user_question: str) -> list[str]:
        lowered = user_question.lower()
        focus: list[str] = []
        if task_type in {"grounded_answer", "grounded_analysis", "grounded_disambiguation"}:
            focus.append("evidence coverage")
        if any(marker in lowered for marker in ("autonomous decision", "decision chain", "source arbitration", "evidence chain")):
            focus.extend(["source arbitration", "chain completeness", "direct support"])
        if any(marker in lowered for marker in ("how many", "count", "number of", "总共", "一共")):
            focus.extend(["duplicate suppression", "entity coverage"])
        if any(marker in lowered for marker in ("how much", "cost", "price", "spent", "paid", "money")):
            focus.extend(["entity-amount binding", "amount completeness"])
        if any(marker in lowered for marker in ("how long", "days", "weeks", "hours", "duration")):
            focus.extend(["unit normalization", "event deduplication"])
        if any(marker in lowered for marker in ("who", "which", "name", "叫什么", "是谁")):
            focus.extend(["candidate separation", "name completeness"])
        if any(marker in lowered for marker in (" in ", " from ", " this year", " last ", " past ", " on monday", " in april", " in december")):
            focus.extend(["time-window alignment", "location alignment"])
        return self._dedupe_strings(focus)

    def _expand_month_range(self, start_month: str, end_month: str) -> list[str]:
        months = [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
        start = months.index(start_month)
        end = months.index(end_month)
        if end >= start:
            return months[start : end + 1]
        return [*months[start:], *months[: end + 1]]

    def _merge_scope_filters(self, base: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "months": self._dedupe_strings(
                [*self._scope_filter_values(base, "months"), *self._scope_filter_values(extra, "months")]
            ),
            "weekdays": self._dedupe_strings(
                [*self._scope_filter_values(base, "weekdays"), *self._scope_filter_values(extra, "weekdays")]
            ),
            "locations": self._dedupe_strings(
                [*self._scope_filter_values(base, "locations"), *self._scope_filter_values(extra, "locations")]
            ),
            "relative_terms": self._dedupe_strings(
                [*self._scope_filter_values(base, "relative_terms"), *self._scope_filter_values(extra, "relative_terms")]
            ),
        }
        merged["strict"] = bool(
            (extra or {}).get("strict")
            or base.get("strict")
            or merged["months"]
            or merged["weekdays"]
            or merged["locations"]
        )
        return merged

    def _default_scope_filters(self, user_question: str) -> dict[str, Any]:
        question = str(user_question or "")
        lowered = question.lower()
        month_names = [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
        weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        blocked_phrases = {
            "How",
            "What",
            "Which",
            "When",
            "Where",
            "Who",
            "Did",
            "I",
            "April",
            "December",
            "January",
            "February",
            "March",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "This Year",
            "Last Year",
        }

        months: list[str] = []
        range_match = re.search(
            r"\bfrom\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+to\s+"
            r"(january|february|march|april|may|june|july|august|september|october|november|december)\b",
            lowered,
        )
        if range_match:
            months.extend(self._expand_month_range(range_match.group(1), range_match.group(2)))
        for month in month_names:
            if re.search(rf"\b{month}\b", lowered):
                months.append(month)

        weekdays = [day for day in weekday_names if re.search(rf"\b{day}\b", lowered)]
        relative_terms = [
            phrase
            for phrase in (
                "this year",
                "last year",
                "this month",
                "last month",
                "this week",
                "last week",
                "past month",
                "past three months",
                "past two months",
                "past four months",
                "last four months",
                "last three months",
                "last two months",
            )
            if phrase in lowered
        ]

        location_candidates: list[str] = []
        location_spans = re.findall(
            r"\b(?:in|at|to|from|between|near)\s+((?:[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})(?:\s+(?:and|,)\s+(?:[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2}))*)",
            question,
        )
        for span in location_spans:
            location_candidates.extend(re.split(r"\s+(?:and|,)\s+", span))
        for phrase in re.findall(r"\b(?:[A-Z][A-Za-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-z]+|[A-Z]{2,})){0,2}\b", question):
            normalized = phrase.strip()
            if normalized in blocked_phrases:
                continue
            if normalized.lower() in month_names or normalized.lower() in weekday_names:
                continue
            location_candidates.append(normalized)

        locations = self._dedupe_strings(location_candidates)
        location_strict = len(locations) >= 2 or any(
            marker in lowered
            for marker in ("travel", "trip", "road trip", "vacation", "commute", "university", "campus")
        )
        return {
            "months": self._dedupe_strings(months),
            "weekdays": self._dedupe_strings(weekdays),
            "locations": locations,
            "relative_terms": self._dedupe_strings(relative_terms),
            "strict": bool(months or weekdays or location_strict),
        }

    def plan_task(
        self,
        user_question: str,
        task_type: str,
        executor_role: str,
        planner_strategy: str,
        query_variants: list[str],
    ) -> PlannerModelPlan:
        fallback = PlannerModelPlan(
            task_description=user_question.strip(),
            query_variants=self._dedupe_strings(query_variants),
            topic_hints=[],
            recent_count=0,
            expected_output_format=self._default_output_format(task_type),
            reasoning_hint=self._default_reasoning_hint(user_question, planner_strategy),
            sub_tasks=self._default_sub_tasks(task_type, user_question),
            verification_focus=self._default_verification_focus(task_type, user_question),
            scope_filters=self._default_scope_filters(user_question),
        )
        if self.model_interface is None:
            return fallback

        prompt = (
            "你是 MASE 的 Planner。请基于当前用户任务和会话摘要，输出严格 JSON 规划。\n"
            "字段：task_description, query_variants, topic_hints, recent_count, expected_output_format, reasoning_hint, sub_tasks, verification_focus, scope_filters。\n"
            "规则：\n"
            "1. 只输出 JSON。\n"
            "2. query_variants 不超过 5 条，topic_hints 不超过 3 条。\n"
            "3. recent_count 只返回 0-5 的整数。\n"
            "4. sub_tasks 不超过 4 条，verification_focus 不超过 4 条。\n"
            "5. scope_filters 只允许包含 months, weekdays, locations, relative_terms, strict。\n"
            "6. 不要编造事实，只做检索/执行规划。\n\n"
            f"会话摘要：{self.session_summary or '(空)'}\n"
            f"用户问题：{user_question}\n"
            f"任务类型：{task_type}\n"
            f"执行角色：{executor_role}\n"
            f"启发式策略：{planner_strategy}\n"
            f"已有检索表达：{query_variants}"
        )
        planning_mode = (
            "retrieval_verification"
            if task_type in {"grounded_answer", "grounded_analysis", "grounded_disambiguation"}
            and planner_strategy in {"query_rewrite_lookup", "disambiguation", "zoom_in_out"}
            else "task_planning"
        )
        response = self.model_interface.chat(
            "planner",
            messages=[{"role": "user", "content": prompt}],
            mode=planning_mode,
        )
        parsed = self._parse_json_object(response["message"]["content"])
        if not parsed:
            return fallback

        return PlannerModelPlan(
            task_description=str(parsed.get("task_description") or fallback.task_description).strip(),
            query_variants=self._dedupe_strings(
                [*fallback.query_variants, *[str(item) for item in parsed.get("query_variants", [])]]
            )[:5],
            topic_hints=self._dedupe_strings([str(item) for item in parsed.get("topic_hints", [])])[:3],
            recent_count=max(0, min(5, int(parsed.get("recent_count") or 0))),
            expected_output_format=str(parsed.get("expected_output_format") or fallback.expected_output_format).strip(),
            reasoning_hint=str(parsed.get("reasoning_hint") or fallback.reasoning_hint).strip(),
            sub_tasks=self._dedupe_strings([*fallback.sub_tasks, *[str(item) for item in parsed.get("sub_tasks", [])]])[:4],
            verification_focus=self._dedupe_strings(
                [*fallback.verification_focus, *[str(item) for item in parsed.get("verification_focus", [])]]
            )[:4],
            scope_filters=self._merge_scope_filters(fallback.scope_filters, parsed.get("scope_filters") if isinstance(parsed.get("scope_filters"), dict) else None),
        )

    def build_instruction_package(
        self,
        user_question: str,
        task_type: str,
        fact_sheet: str,
        planner_strategy: str,
        model_plan: PlannerModelPlan | None = None,
    ) -> InstructionPackage:
        effective_plan = model_plan or PlannerModelPlan(
            task_description=user_question,
            query_variants=[],
            topic_hints=[],
            recent_count=0,
            expected_output_format=self._default_output_format(task_type),
            reasoning_hint=self._default_reasoning_hint(user_question, planner_strategy),
            sub_tasks=self._default_sub_tasks(task_type, user_question),
            verification_focus=self._default_verification_focus(task_type, user_question),
            scope_filters=self._default_scope_filters(user_question),
        )
        return InstructionPackage(
            task_description=effective_plan.task_description or user_question,
            fact_sheet=fact_sheet,
            expected_output_format=effective_plan.expected_output_format,
            reasoning_hint=effective_plan.reasoning_hint,
            background_summary=self.session_summary,
            sub_tasks=effective_plan.sub_tasks,
            verification_focus=effective_plan.verification_focus,
            scope_filters=effective_plan.scope_filters,
        )

    def update_session_summary(
        self,
        user_question: str,
        answer: str,
        instruction_package: InstructionPackage | None = None,
    ) -> str:
        fallback = f"{(self.session_summary + '；') if self.session_summary else ''}{user_question[:40]} -> {answer[:60]}".strip("；")
        fallback = fallback[:240]
        if self.model_interface is None:
            self.session_summary = fallback
            return self.session_summary

        prompt = (
            "你是 MASE 的会话摘要器。请把旧摘要与本轮任务结果融合成新的轻量会话摘要，不超过 180 个中文字符。\n"
            "只输出摘要文本，不要解释。\n\n"
            f"旧摘要：{self.session_summary or '(空)'}\n"
            f"任务描述：{instruction_package.task_description if instruction_package else user_question}\n"
            f"用户问题：{user_question}\n"
            f"系统回答：{answer}"
        )
        response = self.model_interface.chat(
            "planner",
            messages=[{"role": "user", "content": prompt}],
            mode="session_summary",
        )
        summary = response["message"]["content"].strip().replace("\n", " ")
        self.session_summary = (summary if self._is_usable_summary(summary) else fallback)[:180]
        return self.session_summary
