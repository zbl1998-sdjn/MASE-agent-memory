from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from memory_heat import resolve_memory_heat
from planner_agent import InstructionPackage, PlannerModelPlan
from planner import PlannerDecision, PlannerStep, build_planner_decision, refine_planner_with_confusion
from protocol import make_message
from reasoning_engine import build_reasoning_workspace
from router import _extract_keywords_from_question, _should_force_search_memory
from topic_threads import ThreadContext, derive_thread_context
from mase_tools.legacy import (
    _expand_temporal_candidate_search_terms,
    _extract_temporal_candidate_phrases,
    _looks_like_non_location_scope_candidate,
    _looks_like_disambiguation_question,
    _score_result_against_candidate,
    _score_result_against_question_focus,
    _extract_state_time_intent,
    _should_preserve_retrieval_order_for_evidence,
    assess_evidence_chain,
    assess_question_contracts,
    extract_question_scope_filters,
    focus_search_results,
    plan_temporal_date_hints,
)


@dataclass(frozen=True)
class RouteDecision:
    action: str
    keywords: list[str]


@dataclass(frozen=True)
class ExecutionPlan:
    task_type: str
    executor_mode: str
    executor_role: str
    use_memory: bool
    allow_general_knowledge: bool


@dataclass(frozen=True)
class OrchestrationTrace:
    route: RouteDecision
    plan: ExecutionPlan
    planner: PlannerDecision
    planner_steps: list[PlannerStep]
    search_results: list[dict[str, Any]]
    fact_sheet: str
    evidence_assessment: dict[str, Any] | None
    evidence_thresholds: dict[str, Any] | None
    answer: str
    summary: str
    record_path: str
    thread: ThreadContext
    executor_target: dict[str, Any]
    memory_heat: str | None
    planner_model_plan: dict[str, Any] | None
    instruction_package: dict[str, Any] | None
    reasoning_workspace: dict[str, Any] | None
    retrieval_iterations: int
    retrieval_queries: list[str]
    session_summary_before: str
    session_summary_after: str
    messages: list[dict[str, Any]]


class NotetakerPort(Protocol):
    def search(
        self,
        keywords: list[str],
        full_query: str | None = None,
        date_hint: str | None = None,
        top_k: int | None = None,
        limit: int | None = None,
        thread_hint: str | None = None,
        semantic_query: str | None = None,
        query_variants: list[str] | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def build_fact_sheet(
        self,
        results: list[dict[str, Any]],
        question: str | None = None,
        evidence_thresholds: dict[str, Any] | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> str: ...

    def write(
        self,
        user_query: str,
        assistant_response: str,
        summary: str,
        key_entities: list[str] | None = None,
        thread_id: str | None = None,
        thread_label: str | None = None,
        topic_tokens: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str: ...

    def list_dates(self) -> list[str]: ...

    def fetch_recent_records(self, n: int = 5) -> list[dict[str, Any]]: ...

    def fetch_records_by_topic(self, topic: str, limit: int | None = None) -> list[dict[str, Any]]: ...


class PlannerPort(Protocol):
    def get_session_summary(self) -> str: ...

    def plan_task(
        self,
        user_question: str,
        task_type: str,
        executor_role: str,
        planner_strategy: str,
        query_variants: list[str],
    ) -> PlannerModelPlan: ...

    def build_instruction_package(
        self,
        user_question: str,
        task_type: str,
        fact_sheet: str,
        planner_strategy: str,
        model_plan: PlannerModelPlan | None = None,
    ) -> InstructionPackage: ...

    def update_session_summary(
        self,
        user_question: str,
        answer: str,
        instruction_package: InstructionPackage | None = None,
    ) -> str: ...


class ExecutorTargetResolver(Protocol):
    def __call__(
        self,
        mode: str,
        user_question: str,
        use_memory: bool,
        memory_heat: str | None = None,
        executor_role: str | None = None,
    ) -> dict[str, Any]: ...


def _contains_any(text: str, markers: list[str]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _contains_code_marker(text: str, markers: list[str]) -> bool:
    lowered = text.lower()
    for marker in markers:
        normalized = marker.lower().strip()
        if not normalized:
            continue
        if re.search(r"[\u4e00-\u9fff]", normalized):
            if normalized in lowered:
                return True
            continue
        if " " in normalized:
            if normalized in lowered:
                return True
            continue
        if re.search(rf"\b{re.escape(normalized)}\b", lowered):
            return True
    return False


def _looks_like_math_request(question: str) -> bool:
    math_markers = [
        "计算",
        "算一下",
        "求",
        "解方程",
        "积分",
        "导数",
        "概率",
        "矩阵",
        "微分",
        "方程",
    ]
    if _contains_any(question, math_markers):
        return True
    return bool(re.search(r"[\d\)\(][\d\s\(\)]*[\+\-\*/%=][\d\s\(\)\+\-\*/%=\.]*\d", question))


def _looks_like_reasoning_request(question: str) -> bool:
    lowered = question.lower()
    markers = [
        "总共",
        "一共",
        "合计",
        "对比",
        "比较",
        "分析",
        "统计",
        "计算",
        "加起来",
        "分别",
        "各自",
        "多少个",
        "多少次",
        "多少小时",
        "多长时间",
        "几次",
        "几天",
        "几周",
        "几小时",
        "count",
        "compare",
        "analysis",
        "analyze",
        "calculate",
        "calculation",
        "in total",
        "combined",
        "how many",
        "how much",
        "how long",
        "how old",
        "what time",
        "at which",
        "minimum amount",
        "maximum amount",
        "happened first",
        "happened last",
        "which event",
        "which item",
        "which device",
        "which task",
        "who did i meet",
        "who did i go with",
        "days had passed",
        "days between",
        "between the",
        "used to",
        "when i started",
        "at first",
        "back then",
        "previously",
        "currently",
        "first, second and third",
        "day before",
        "before i had",
        "total",
        "sum",
        "difference",
        "multi-hop",
        "autonomous decision",
        "decision chain",
        "source arbitration",
        "evidence chain",
    ]
    return any(marker in lowered for marker in markers)


def _is_english_question(question: str) -> bool:
    ascii_letters = len(re.findall(r"[A-Za-z]", question))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", question))
    return ascii_letters > chinese_chars


def classify_executor_task(user_question: str, route_action: str) -> str:
    question = user_question.strip()
    if not question:
        return "general_answer"

    code_markers = [
        "代码",
        "脚本",
        "函数",
        "类",
        "接口",
        "组件",
        "SQL",
        "正则",
        "配置字典",
        "python",
        "javascript",
        "typescript",
        "java",
        "golang",
        "go语言",
        "rust",
        "bash",
        "shell",
    ]
    structured_markers = [
        "总结",
        "整理",
        "归纳",
        "提取",
        "改写",
        "翻译",
        "列出",
        "转换",
        "改成",
        "生成json",
        "表格",
    ]

    if _contains_code_marker(question, code_markers):
        return "code_generation"
    if _looks_like_math_request(question):
        return "math_compute"
    if _contains_any(question, structured_markers):
        return "structured_task"
    if route_action == "search_memory":
        if _looks_like_reasoning_request(question):
            return "grounded_analysis"
        return "grounded_answer"
    return "general_answer"


def classify_executor_role(user_question: str, route_action: str, task_type: str) -> str:
    if task_type in {"math_compute", "code_generation"}:
        return "reasoning"
    if task_type == "grounded_analysis":
        return "reasoning"
    if task_type == "grounded_answer":
        return "reasoning" if _looks_like_reasoning_request(user_question) else "general"
    if task_type in {"structured_task", "general_answer"}:
        return "reasoning" if _looks_like_reasoning_request(user_question) else "general"
    if route_action == "search_memory":
        return "general"
    return "general"


def _combine_entities(route: RouteDecision, thread: ThreadContext) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in route.keywords + thread.topic_tokens:
        normalized = str(item).strip()
        if not normalized or normalized == "__FULL_QUERY__":
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(normalized)
    return result[:6]


def _search_result_preview(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for item in results[:3]:
        preview.append(
            {
                "filepath": item.get("filepath"),
                "summary": item.get("summary"),
                "thread_id": item.get("thread_id"),
                "thread_label": item.get("thread_label"),
            }
        )
    return preview


def _merge_search_results(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    *,
    keep_order: bool = False,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in primary + secondary:
        filepath = str(item.get("filepath") or "")
        if not filepath or filepath in seen:
            continue
        seen.add(filepath)
        merged.append(item)
    if not keep_order:
        merged.sort(key=lambda item: (item.get("date", ""), item.get("time", ""), str(item.get("filepath", ""))), reverse=True)
    return merged


def _merge_strings(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in primary + secondary:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        merged.append(normalized)
    return merged


def _interleave_expansion_groups(seeds: list[str], expansion_groups: list[list[str]], max_depth: int) -> list[str]:
    queries: list[str] = list(seeds)
    for depth in range(max_depth):
        for group in expansion_groups:
            if depth < len(group):
                queries.append(group[depth])
    return _merge_strings(queries, [])


def _temporal_candidate_followup_queries(user_question: str) -> list[str]:
    candidates = _extract_temporal_candidate_phrases(user_question)[:4]
    expansion_groups = [
        [query for query in _expand_temporal_candidate_search_terms(candidate) if query.lower() != candidate.lower()]
        for candidate in candidates
    ]
    return _interleave_expansion_groups(candidates, expansion_groups, 4 if len(candidates) <= 1 else 2)[:8]


def _merge_scope_filters(user_question: str, planner_scope_filters: dict[str, Any] | None) -> dict[str, Any]:
    lowered_question = user_question.lower()
    base_filters = extract_question_scope_filters(user_question)
    planner_filters = planner_scope_filters if isinstance(planner_scope_filters, dict) else {}
    months = _merge_strings(
        [str(item) for item in base_filters.get("months", []) if str(item).strip()],
        [str(item) for item in planner_filters.get("months", []) if str(item).strip()],
    )
    weekdays = _merge_strings(
        [str(item) for item in base_filters.get("weekdays", []) if str(item).strip()],
        [str(item) for item in planner_filters.get("weekdays", []) if str(item).strip()],
    )
    blocked_locations = {item.lower() for item in months + weekdays}
    locations = [
        location
        for location in _merge_strings(
            [str(item) for item in base_filters.get("locations", []) if str(item).strip()],
            [str(item) for item in planner_filters.get("locations", []) if str(item).strip()],
        )
        if location.lower() not in blocked_locations
        and not _looks_like_non_location_scope_candidate(location)
    ]
    relative_terms = _merge_strings(
        [str(item) for item in base_filters.get("relative_terms", []) if str(item).strip()],
        [str(item) for item in planner_filters.get("relative_terms", []) if str(item).strip()],
    )
    timeline_anchor_question = (
        len(_extract_temporal_candidate_phrases(user_question)) >= 2
        and (
            "happened first" in lowered_question
            or re.search(r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+ago\s+did i\s+.+\s+when i\s+.+", lowered_question)
            or re.search(r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+(?:had|have)\s+passed since i\s+.+\s+when i\s+.+", lowered_question)
            or re.search(r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+passed since i\s+.+\s+when i\s+.+", lowered_question)
        )
    )
    if timeline_anchor_question:
        locations = []
    strict = bool(
        months
        or weekdays
        or locations
        or base_filters.get("strict")
        or planner_filters.get("strict")
    )
    if timeline_anchor_question and not (months or weekdays or relative_terms):
        strict = False
    return {
        "months": months,
        "weekdays": weekdays,
        "locations": locations,
        "relative_terms": relative_terms,
        "strict": strict,
    }


def _looks_like_aggregation_question(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(
        marker in lowered
        for marker in (
            "how many",
            "how much",
            "how long",
            "total",
            "combined",
            "altogether",
            "in total",
            "difference",
            "spent",
            "raised",
            "earned",
            "sold",
            "increase",
            "decrease",
            "change",
            "delta",
            "gain",
            "gained",
            "previous",
            "previously",
            "used to",
            "when i started",
            "currently",
            "current",
        )
    )


def _looks_like_delta_question(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(marker in lowered for marker in ("increase", "decrease", "change", "delta", "gain", "gained", "lost", "loss"))


def _delta_endpoint_state(user_question: str, results: list[dict[str, Any]]) -> dict[str, bool]:
    lowered_question = str(user_question or "").lower()
    if not _looks_like_delta_question(user_question):
        return {"required": False, "has_start": False, "has_end": False}
    has_start = False
    has_end = False
    for item in results[:8]:
        for field in ("user_query", "summary", "assistant_response"):
            text = str(item.get(field) or "")
            lowered_text = text.lower()
            if "followers" in lowered_question and "followers" in lowered_text:
                if re.search(r"\b(?:started|start(?:ed)?|began|initially|originally)[^.!?\n]*?\bwith\s+\d+(?:\.\d+)?\s+followers\b", lowered_text):
                    has_start = True
                if re.search(r"\bfrom\s+\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\s+followers\b", lowered_text):
                    has_start = True
                    has_end = True
                if re.search(r"\b(?:had|have|having)\s+(?:around\s+)?\d+(?:\.\d+)?\s+followers\b", lowered_text):
                    has_end = True
            else:
                if re.search(r"\bfrom\s+\$?\d+(?:\.\d+)?\s+to\s+\$?\d+(?:\.\d+)?\b", lowered_text):
                    has_start = True
                    has_end = True
                if any(marker in lowered_text for marker in ("started with", "initially", "originally", "before")) and re.search(r"\$?\d+(?:\.\d+)?", lowered_text):
                    has_start = True
                if any(marker in lowered_text for marker in ("after", "now", "currently", "ended", "reached", "had")) and re.search(r"\$?\d+(?:\.\d+)?", lowered_text):
                    has_end = True
    return {"required": True, "has_start": has_start, "has_end": has_end}


def _needs_delta_endpoint_completion(user_question: str, results: list[dict[str, Any]]) -> bool:
    state = _delta_endpoint_state(user_question, results)
    return bool(state["required"] and (not state["has_start"] or not state["has_end"]))


def _is_coverage_bridge_question(user_question: str) -> bool:
    return (
        _is_english_question(user_question)
        and _looks_like_disambiguation_question(user_question)
        and bool(extract_question_scope_filters(user_question).get("locations"))
    )


def _build_coverage_queries(
    user_question: str,
    results: list[dict[str, Any]],
    scope_filters: dict[str, Any],
    fact_sheet: str = "",
) -> list[str]:
    lowered = str(user_question or "").lower()
    state_time_intent = _extract_state_time_intent(user_question)
    scored_queries: dict[str, tuple[str, int, int]] = {}
    if not _looks_like_aggregation_question(user_question):
        return []

    def add_query(raw_query: str, base_score: int = 1) -> None:
        query = str(raw_query or "").strip()
        if not query:
            return
        lowered_query = query.lower()
        if len(lowered_query) <= 2:
            return
        if lowered_query in {"event", "events", "activity", "activities", "thing", "things"}:
            return
        shape_bonus = 1 if (" " in query or any(char.isupper() for char in query)) else 0
        question_bonus = 1 if lowered_query in lowered else 0
        score = base_score + shape_bonus + question_bonus
        existing = scored_queries.get(lowered_query)
        if existing is None:
            scored_queries[lowered_query] = (query, score, 1)
            return
        scored_queries[lowered_query] = (existing[0], max(existing[1], score), existing[2] + 1)

    for item in results[:6]:
        fact_card = item.get("fact_card", {}) if isinstance(item.get("fact_card"), dict) else {}
        if fact_card:
            event_type = str(fact_card.get("event_type") or "").strip()
            if event_type and event_type != "generic":
                add_query(event_type, 1)
            for entity in fact_card.get("entities", [])[:4]:
                add_query(str(entity), 2)
            scope_hints = fact_card.get("scope_hints", {}) if isinstance(fact_card.get("scope_hints"), dict) else {}
            for location in scope_hints.get("locations", [])[:4]:
                add_query(str(location), 2)
        memory_profile = item.get("memory_profile", {}) if isinstance(item.get("memory_profile"), dict) else {}
        for event_card in memory_profile.get("event_cards", [])[:4]:
            if isinstance(event_card, dict):
                display_name = str(event_card.get("display_name") or "").strip()
                event_type = str(event_card.get("event_type") or "").strip()
                if display_name:
                    add_query(display_name, 3)
                    if event_type:
                        add_query(f"{display_name} {event_type}", 3)
        for entity_card in memory_profile.get("entity_cards", [])[:4]:
            if isinstance(entity_card, dict):
                name = str(entity_card.get("name") or "").strip()
                if name:
                    add_query(name, 2)

    if "charity" in lowered or "fundraiser" in lowered:
        for query in ("charity fundraiser", "donation raised", "charity event", "fundraiser donation"):
            add_query(query, 4)
    if "market" in lowered or "products" in lowered:
        for query in ("market sold products", "earned at market", "product sales"):
            add_query(query, 4)
    if "workshop" in lowered or "conference" in lowered or "lecture" in lowered:
        for query in ("workshop cost", "conference cost", "lecture cost", "training workshop"):
            add_query(query, 4)
    if "rollercoaster" in lowered:
        for query in ("rollercoaster rode", "theme park rollercoaster"):
            add_query(query, 4)
    if any(
        state_time_intent.get(flag)
        for flag in ("ask_previous", "ask_current", "ask_transition", "ask_update_resolution", "ask_future_projection")
    ):
        for query in state_time_intent.get("query_hints", []):
            add_query(str(query), 5)
    if _looks_like_delta_question(user_question):
        delta_queries = (
            "before",
            "earlier",
            "started with",
            "initial value",
            "original value",
            "from to",
        )
        for query in delta_queries:
            add_query(query, 4)
        if "followers" in lowered:
            for query in (
                "followers before",
                "started with followers",
                "initial followers",
                "followers earlier",
                "instagram followers before",
            ):
                add_query(query, 5)
    slot_state = _slot_contract_state(user_question, results, fact_sheet)
    prioritized_slot_queries = [str(query).strip() for query in slot_state.get("queries", []) if str(query).strip()]
    for query in prioritized_slot_queries[:6]:
        add_query(query, 9)

    months = [str(item) for item in scope_filters.get("months", []) if str(item).strip()]
    locations = [str(item) for item in scope_filters.get("locations", []) if str(item).strip()]
    for month in months[:4]:
        add_query(month, 3)
    for location in locations[:4]:
        add_query(location, 3)
    for month in months[:3]:
        for location in locations[:3]:
            add_query(f"{location} {month}", 4)
    ranked = sorted(
        scored_queries.values(),
        key=lambda item: (-item[1], -item[2], -len(item[0].split()), len(item[0])),
    )
    ordered: list[str] = []
    seen_queries: set[str] = set()
    for query in prioritized_slot_queries:
        lowered_query = query.lower()
        if lowered_query in seen_queries:
            continue
        seen_queries.add(lowered_query)
        ordered.append(query)
    for query, score, count in ranked:
        if score < 3 and count < 2:
            continue
        lowered_query = query.lower()
        if lowered_query in seen_queries:
            continue
        seen_queries.add(lowered_query)
        ordered.append(query)
    return ordered[:12]


def _coverage_signal_state(results: list[dict[str, Any]]) -> dict[str, int]:
    event_names: set[str] = set()
    entities: set[str] = set()
    locations: set[str] = set()
    months: set[str] = set()
    for item in results[:8]:
        fact_card = item.get("fact_card", {}) if isinstance(item.get("fact_card"), dict) else {}
        if fact_card:
            event_name = str(fact_card.get("event_type") or "").strip().lower()
            if event_name and event_name != "generic":
                event_names.add(event_name)
            for entity in fact_card.get("entities", [])[:6]:
                normalized = str(entity).strip().lower()
                if normalized:
                    entities.add(normalized)
            scope_hints = fact_card.get("scope_hints", {}) if isinstance(fact_card.get("scope_hints"), dict) else {}
            for month in scope_hints.get("months", [])[:4]:
                normalized = str(month).strip().lower()
                if normalized:
                    months.add(normalized)
            for location in scope_hints.get("locations", [])[:4]:
                normalized = str(location).strip().lower()
                if normalized:
                    locations.add(normalized)
    return {
        "event_name_count": len(event_names),
        "entity_count": len(entities),
        "month_count": len(months),
        "location_count": len(locations),
    }


def _extract_fact_sheet_section_items(fact_sheet: str, heading: str) -> list[str]:
    items: list[str] = []
    capture = False
    normalized_heading = heading.strip().lower().rstrip(":")
    for raw_line in str(fact_sheet or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if lowered.startswith("- ") and lowered[2:].strip().rstrip(":") == normalized_heading:
            capture = True
            continue
        if not capture:
            continue
        if re.match(r"- [A-Za-z][A-Za-z0-9 /_\-]+:$", line):
            break
        if not line.startswith("- "):
            continue
        item = re.sub(r"^- (?:\d+\.\s*)?", "", line).strip()
        if item:
            items.append(item)
    return items


def _extract_deterministic_count_value(fact_sheet: str) -> int | None:
    match = re.search(
        r"Deterministic (?:item )?count:\s*(\d+(?:\.\d+)?)",
        str(fact_sheet or ""),
        re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1))
    return int(value) if value.is_integer() else None


def _extract_social_platforms(fact_sheet: str) -> list[str]:
    platforms: list[str] = []
    seen: set[str] = set()
    for match in re.findall(
        r"\b(Instagram|TikTok|YouTube|Twitter|X|Facebook|LinkedIn|Threads|Pinterest|Snapchat|Reddit)\b",
        str(fact_sheet or ""),
        flags=re.IGNORECASE,
    ):
        normalized = str(match).strip()
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        platforms.append(normalized)
    return platforms


def _extract_wedding_identity_names(fact_sheet: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"\b([A-Z][a-z]+)'s wedding\b", str(fact_sheet or "")):
        if match in {"My", "The"}:
            continue
        lowered = match.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        names.append(match)
    for first, _second in re.findall(r"\b([A-Z][a-z]+)\s+and\s+([A-Z][a-z]+)\b", str(fact_sheet or "")):
        lowered = first.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        names.append(first)
    return names


def _delta_slot_contract_state(user_question: str, fact_sheet: str) -> dict[str, Any]:
    lowered = str(user_question or "").lower()
    if not _looks_like_delta_question(user_question):
        return {"required": False, "complete": True, "queries": [], "reason": ""}
    source = str(fact_sheet or "")
    has_start = bool(
        re.search(r"\bfollowers_start=", source, re.IGNORECASE)
        or re.search(r"\bdelta_left=", source, re.IGNORECASE)
        or re.search(r"Deterministic money delta:\s*.*\$\d[\d,]*(?:\.\d+)?\s*-\s*.*\$\d", source, re.IGNORECASE)
    )
    has_end = bool(
        re.search(r"\bfollowers_end=", source, re.IGNORECASE)
        or re.search(r"\bdelta_right=", source, re.IGNORECASE)
        or re.search(r"Deterministic money delta:\s*.*\$\d[\d,]*(?:\.\d+)?\s*-\s*.*\$\d", source, re.IGNORECASE)
    )
    queries: list[str] = []
    if not has_start:
        queries.extend(["before", "earlier", "started with", "initial value", "original value"])
        if "followers" in lowered:
            queries.extend(["followers before", "started with followers", "initial followers"])
    if not has_end:
        queries.extend(["after", "current value", "now", "currently", "ended with"])
        if "followers" in lowered:
            queries.extend(["followers now", "current followers", "followers after"])
    return {
        "required": True,
        "complete": has_start and has_end,
        "queries": queries,
        "reason": "" if has_start and has_end else "delta-slot-gap",
    }


def _remaining_slot_contract_state(user_question: str, fact_sheet: str) -> dict[str, Any]:
    lowered = str(user_question or "").lower()
    if not any(marker in lowered for marker in ("left", "remaining", "still need", "need to", "more")):
        return {"required": False, "complete": True, "queries": [], "reason": ""}
    source = str(fact_sheet or "")
    has_total = bool(re.search(r"\btotal=", source, re.IGNORECASE) or re.search(r"\bwhole=", source, re.IGNORECASE))
    has_current = bool(re.search(r"\bcurrent=", source, re.IGNORECASE))
    has_direct_remaining = bool(
        re.search(r"Deterministic scalar remaining:\s*direct remaining value", source, re.IGNORECASE)
        or (re.search(r"\bremaining=", source, re.IGNORECASE) and not (has_total or has_current))
    )
    complete = has_direct_remaining or (has_total and has_current)
    queries: list[str] = []
    if not complete:
        if not has_total:
            queries.extend(["goal total", "target total", "required total"])
        if not has_current:
            queries.extend(["current progress", "so far", "currently at", "already completed"])
        queries.append("remaining left to go")
    return {
        "required": True,
        "complete": complete,
        "queries": queries,
        "reason": "" if complete else "remaining-slot-gap",
    }


def _percentage_slot_contract_state(user_question: str, fact_sheet: str) -> dict[str, Any]:
    lowered = str(user_question or "").lower()
    if "%" not in lowered and "percent" not in lowered and "percentage" not in lowered and "discount" not in lowered:
        return {"required": False, "complete": True, "queries": [], "reason": ""}
    source = str(fact_sheet or "")
    has_direct_percentage = bool(re.search(r"\bpercentage=", source, re.IGNORECASE))
    has_part = bool(re.search(r"\bpart=", source, re.IGNORECASE))
    has_whole = bool(re.search(r"\bwhole=", source, re.IGNORECASE))
    has_compared = bool(re.search(r"compared percentages=", source, re.IGNORECASE))
    if "compared to" in lowered and lowered.startswith("did "):
        complete = has_compared
    else:
        complete = has_direct_percentage or (has_part and has_whole)
    queries: list[str] = []
    if not complete:
        if "discount" in lowered:
            queries.append("discount percentage")
        if "compared to" in lowered:
            queries.append("compared percentages")
        if not has_part:
            queries.append("percentage part value")
        if not has_whole:
            queries.append("percentage whole value")
        queries.append("percentage rate")
    return {
        "required": True,
        "complete": complete,
        "queries": queries,
        "reason": "" if complete else "percentage-slot-gap",
    }


def _slot_contract_state(
    user_question: str,
    results: list[dict[str, Any]],
    fact_sheet: str,
) -> dict[str, Any]:
    return assess_question_contracts(user_question, results, fact_sheet)


def _should_start_coverage_loop(
    user_question: str,
    results: list[dict[str, Any]],
    fact_sheet: str,
    evidence_assessment: dict[str, Any] | None,
) -> bool:
    bridge_question = _is_coverage_bridge_question(user_question)
    if not _looks_like_aggregation_question(user_question):
        if not bridge_question or evidence_assessment is None:
            return False
        return evidence_assessment.get("verifier_action") in {"verify", "refuse"}
    if (
        _should_preserve_retrieval_order_for_evidence(user_question)
        and re.search(
            r"Deterministic (?:scalar value|state transition|item count|count|chronology)",
            str(fact_sheet or ""),
            re.IGNORECASE,
        )
    ):
        return False
    if _needs_delta_endpoint_completion(user_question, results):
        return True
    if _slot_contract_state(user_question, results, fact_sheet).get("incomplete"):
        return True
    if evidence_assessment is None:
        return False
    return evidence_assessment.get("verifier_action") in {"verify", "refuse"}


def _should_continue_coverage_loop(
    user_question: str,
    results: list[dict[str, Any]],
    fact_sheet: str,
    evidence_assessment: dict[str, Any] | None,
    retrieval_iterations: int,
    new_result_count: int,
) -> bool:
    bridge_question = _is_coverage_bridge_question(user_question)
    delta_gap = _needs_delta_endpoint_completion(user_question, results)
    slot_gap = bool(_slot_contract_state(user_question, results, fact_sheet).get("incomplete"))
    if evidence_assessment is None and not delta_gap and not slot_gap:
        return False
    if not delta_gap and not slot_gap and evidence_assessment.get("verifier_action") not in {"verify", "refuse"}:
        return False
    if retrieval_iterations >= 3:
        return False
    if not _looks_like_aggregation_question(user_question):
        if not bridge_question:
            return False
        return new_result_count > 0 and evidence_assessment.get("verifier_action") in {"verify", "refuse"}
    if new_result_count <= 0:
        return False
    if delta_gap or slot_gap:
        return True
    lowered = str(user_question or "").lower()
    broad_aggregation = any(
        marker in lowered
        for marker in ("all", "across all", "in total", "altogether", "combined", "total amount", "total weight", "total distance")
    )
    signal_state = _coverage_signal_state(results)
    if len(results) < 3:
        return True
    if broad_aggregation and (signal_state["event_name_count"] + signal_state["entity_count"]) < 3:
        return True
    return evidence_assessment.get("verifier_action") == "verify" and retrieval_iterations < 3


def calculate_dynamic_threshold(
    user_question: str,
    plan: ExecutionPlan,
    planner: PlannerDecision,
    search_results: list[dict[str, Any]],
) -> dict[str, Any]:
    benchmark_profile = str(os.environ.get("MASE_BENCHMARK_PROFILE") or "").strip().lower()
    external_generalization = bool(
        benchmark_profile
        and (
            benchmark_profile in {"external_generalization", "external-generalization", "bamboo", "nolima"}
            or benchmark_profile.startswith("external_")
            or benchmark_profile.startswith("bamboo")
            or benchmark_profile.startswith("nolima")
        )
    )
    profile: dict[str, Any] = {"profile_name": "default"}
    lowered_question = user_question.lower()
    ascii_letters = len(re.findall(r"[A-Za-z]", user_question))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", user_question))
    english_question = ascii_letters > chinese_chars
    english_aggregation = english_question and any(
        marker in lowered_question
        for marker in (
            "how many",
            "how much",
            "how long",
            "in total",
            "combined",
            "total",
            "sum",
        )
    )
    result_count = len(search_results)

    if external_generalization and english_question and plan.use_memory:
        profile = {
            "profile_name": "external-generalization",
            "general_pass_evidence_items_min": 1,
            "general_pass_snippet_total_min": 1 if result_count <= 2 else 2,
            "general_verify_evidence_items_min": 1,
        }
        if plan.task_type == "grounded_answer" and planner.strategy == "disambiguation":
            profile.update(
                {
                    "disambiguation_pass_score_min": 130 if result_count <= 3 else 138,
                    "disambiguation_pass_score_gap_min": 28 if result_count <= 3 else 34,
                    "disambiguation_verify_score_min": 95 if result_count <= 3 else 105,
                    "disambiguation_verify_score_gap_min": 16 if result_count <= 3 else 22,
                    "allow_verify_on_multiple_direct_matches": True,
                    "multiple_direct_matches_verify_top_score_min": 190 if result_count <= 3 else 205,
                    "multiple_direct_matches_verify_score_gap_min": 22 if result_count <= 3 else 30,
                }
            )
        return profile

    if english_question and plan.use_memory:
        general_pass_evidence_items_min = 1 if result_count <= 2 else 2
        general_pass_snippet_total_min = 2 if english_aggregation else 2 if result_count <= 2 else 3
        profile = {
            "profile_name": "english-memory-dynamic",
            "general_pass_evidence_items_min": general_pass_evidence_items_min,
            "general_pass_snippet_total_min": general_pass_snippet_total_min,
            "general_verify_evidence_items_min": 1,
        }
        if english_aggregation:
            profile["profile_name"] = "english-aggregation-dynamic"
            profile["general_pass_snippet_total_min"] = 2

        if plan.task_type == "grounded_answer" and planner.strategy == "disambiguation":
            profile.update(
                {
                    "disambiguation_pass_score_min": 140 if result_count <= 3 else 145,
                    "disambiguation_pass_score_gap_min": 40 if result_count <= 3 else 48,
                    "disambiguation_verify_score_min": 100 if result_count <= 3 else 110,
                    "disambiguation_verify_score_gap_min": 22 if result_count <= 3 else 28,
                    "allow_verify_on_multiple_direct_matches": True,
                    "multiple_direct_matches_verify_top_score_min": 210 if result_count <= 3 else 220,
                    "multiple_direct_matches_verify_score_gap_min": 30 if result_count <= 3 else 38,
                }
            )
            if planner.confusion_level == "high":
                profile["profile_name"] = "english-disambiguation-high-dynamic"
                profile["disambiguation_pass_score_gap_min"] = 34
                profile["disambiguation_verify_score_gap_min"] = 18
            elif planner.confusion_level == "medium":
                profile["profile_name"] = "english-disambiguation-medium-dynamic"
                profile["disambiguation_pass_score_gap_min"] = 38
                profile["disambiguation_verify_score_gap_min"] = 20
        return profile

    if plan.task_type != "grounded_answer" or planner.strategy != "disambiguation":
        return profile

    profile = {
        "profile_name": "disambiguation-guarded",
        "disambiguation_pass_score_min": 150,
        "disambiguation_pass_score_gap_min": 70,
        "disambiguation_verify_score_min": 120,
        "disambiguation_verify_score_gap_min": 30,
        "allow_verify_on_multiple_direct_matches": False,
        "multiple_direct_matches_verify_top_score_min": 230,
        "multiple_direct_matches_verify_score_gap_min": 60,
    }
    if planner.confusion_level == "high":
        profile["profile_name"] = "disambiguation-high-confusion"
        profile["allow_verify_on_multiple_direct_matches"] = True
        profile["multiple_direct_matches_verify_top_score_min"] = 240
        profile["multiple_direct_matches_verify_score_gap_min"] = 45
    elif planner.confusion_level == "medium":
        profile["profile_name"] = "disambiguation-medium-confusion"
        profile["allow_verify_on_multiple_direct_matches"] = True
        profile["multiple_direct_matches_verify_top_score_min"] = 230
        profile["multiple_direct_matches_verify_score_gap_min"] = 55

    if len(search_results) <= 2:
        profile["multiple_direct_matches_verify_top_score_min"] = max(
            220,
            int(profile["multiple_direct_matches_verify_top_score_min"]) - 10,
        )
    if any(marker in lowered_question for marker in ("是谁", "叫什么", "哪位", "名字", "who", "name")):
        profile["profile_name"] = f"{profile['profile_name']}-name-lookup"
    return profile


class MASEOrchestrator:
    def __init__(
        self,
        router: Callable[[str], dict[str, Any]],
        executor: Callable[..., str],
        summarizer: Callable[[str, str], str],
        notetaker: NotetakerPort,
        memory_result_limit: Callable[[str], int | None],
        executor_target_resolver: ExecutorTargetResolver | None = None,
        planner_agent: PlannerPort | None = None,
    ) -> None:
        self.router = router
        self.executor = executor
        self.summarizer = summarizer
        self.notetaker = notetaker
        self.memory_result_limit = memory_result_limit
        self.executor_target_resolver = executor_target_resolver
        self.planner_agent = planner_agent

    def _normalize_route(self, raw_route: dict[str, Any]) -> RouteDecision:
        action = str(raw_route.get("action", "direct_answer"))
        keywords = raw_route.get("keywords") or []
        normalized_keywords = [
            str(keyword).strip()
            for keyword in keywords
            if isinstance(keyword, str) and keyword.strip()
        ]
        return RouteDecision(action=action, keywords=normalized_keywords[:3])

    def build_execution_plan(self, user_question: str, route: RouteDecision) -> ExecutionPlan:
        task_type = classify_executor_task(user_question, route.action)
        executor_role = classify_executor_role(user_question, route.action, task_type)
        use_memory = route.action == "search_memory"
        allow_general_knowledge = not use_memory or task_type in {
            "code_generation",
            "math_compute",
            "structured_task",
        }
        return ExecutionPlan(
            task_type=task_type,
            executor_mode=task_type,
            executor_role=executor_role,
            use_memory=use_memory,
            allow_general_knowledge=allow_general_knowledge,
        )

    def _resolve_executor_target(
        self,
        mode: str,
        user_question: str,
        use_memory: bool,
        memory_heat: str | None,
        executor_role: str | None = None,
    ) -> dict[str, Any]:
        if self.executor_target_resolver is None:
            return {"mode": mode, "memory_heat": memory_heat, "executor_role": executor_role}
        return self.executor_target_resolver(
            mode=mode,
            user_question=user_question,
            use_memory=use_memory,
            memory_heat=memory_heat,
            executor_role=executor_role,
        )

    def run_with_trace(
        self,
        user_question: str,
        log: bool = True,
        forced_route: dict[str, Any] | None = None,
    ) -> OrchestrationTrace:
        route_source = "router"
        if forced_route is not None:
            route = self._normalize_route(forced_route)
            route_source = "forced"
        else:
            route = self._normalize_route(self.router(user_question))
        if route.action == "direct_answer" and _should_force_search_memory(user_question):
            route = RouteDecision(action="search_memory", keywords=_extract_keywords_from_question(user_question) or ["__FULL_QUERY__"])
            route_source = "guard"
        base_thread = derive_thread_context(user_question, route.keywords)
        messages = [
            make_message(
                kind="route_request",
                source="user",
                target="router",
                payload={"question": user_question},
                thread_id=base_thread.thread_id,
            ).to_dict()
        ]

        if log:
            prefix = "[路由-强制]" if route_source == "forced" else "[路由]"
            print(f"{prefix} 决策: {{'action': '{route.action}', 'keywords': {route.keywords}}}")
        messages.append(
            make_message(
                kind="route_decision",
                source=route_source,
                target="orchestrator",
                payload={"action": route.action, "keywords": route.keywords},
                thread_id=base_thread.thread_id,
            ).to_dict()
        )

        plan = self.build_execution_plan(user_question, route)
        planner = build_planner_decision(
            user_question=user_question,
            route_action=route.action,
            route_keywords=route.keywords,
            task_type=plan.task_type,
            executor_role=plan.executor_role,
            use_memory=plan.use_memory,
            base_memory_limit=self.memory_result_limit(user_question) if plan.use_memory else None,
        )
        session_summary_before = self.planner_agent.get_session_summary() if self.planner_agent else ""
        planner_model_plan = (
            self.planner_agent.plan_task(
                user_question=user_question,
                task_type=plan.task_type,
                executor_role=plan.executor_role,
                planner_strategy=planner.strategy,
                query_variants=planner.query_variants,
            )
            if self.planner_agent is not None
            else None
        )
        effective_query_variants = _merge_strings(
            planner.query_variants,
            planner_model_plan.query_variants if planner_model_plan else [],
        )
        scope_filters = _merge_scope_filters(
            user_question,
            dict(planner_model_plan.scope_filters)
            if planner_model_plan is not None and getattr(planner_model_plan, "scope_filters", None)
            else None,
        )
        retrieval_queries = list(effective_query_variants)
        retrieval_iterations = 1
        planner_steps = planner.steps
        if log:
            print(
                "[编排] 执行计划: "
                f"task_type={plan.task_type}, executor_role={plan.executor_role}, use_memory={plan.use_memory}, "
                f"allow_general_knowledge={plan.allow_general_knowledge}"
            )
            print(
                "[规划] 决策: "
                f"strategy={planner.strategy}, memory_limit={planner.memory_limit}, "
                f"collaboration={planner.collaboration_mode}, date_scan={planner.active_date_scan}"
            )
            print("[规划] 步骤: " + " -> ".join(step.title for step in planner_steps))
        messages.append(
            make_message(
                kind="planning_result",
                source="orchestrator",
                target="executor",
                payload=planner.to_dict(),
                thread_id=base_thread.thread_id,
            ).to_dict()
        )

        search_results: list[dict[str, Any]] = []
        fact_sheet = ""
        evidence_assessment: dict[str, Any] | None = None
        evidence_thresholds: dict[str, Any] | None = None
        english_memory_aids: dict[str, list[str]] | None = None
        reasoning_workspace_payload: dict[str, Any] | None = None
        coverage_iterations: list[dict[str, Any]] = []
        resolved_thread = base_thread
        memory_heat: str | None = None
        english_question = _is_english_question(user_question)
        effective_executor_mode = plan.executor_mode
        effective_executor_role = plan.executor_role
        effective_collaboration_mode = planner.collaboration_mode
        preserve_retrieval_order = _should_preserve_retrieval_order_for_evidence(user_question)
        if plan.use_memory:
            memory_limit = planner.memory_limit
            messages.append(
                make_message(
                    kind="memory_query",
                    source="orchestrator",
                    target="notetaker",
                    payload={
                        "keywords": route.keywords,
                        "full_query": user_question if "__FULL_QUERY__" in route.keywords else None,
                        "limit": memory_limit,
                        "query_variants": effective_query_variants,
                        "topic_hints": planner_model_plan.topic_hints if planner_model_plan else [],
                        "recent_count": planner_model_plan.recent_count if planner_model_plan else 0,
                        "scope_filters": scope_filters,
                    },
                    thread_id=base_thread.thread_id,
                ).to_dict()
            )
            search_results = self.notetaker.search(
                route.keywords,
                full_query=user_question if "__FULL_QUERY__" in route.keywords else None,
                limit=memory_limit,
                thread_hint=base_thread.thread_id,
                semantic_query=user_question,
                query_variants=effective_query_variants,
                scope_filters=scope_filters,
            )
            if english_question:
                english_followup_variants = _merge_strings(effective_query_variants, [user_question])
                if hasattr(self.notetaker, "build_english_followup_queries"):
                    english_followup_variants = _merge_strings(
                        english_followup_variants,
                        getattr(self.notetaker, "build_english_followup_queries")(user_question, search_results),
                    )
                retrieval_queries = _merge_strings(retrieval_queries, english_followup_variants)
                english_followup_results = self.notetaker.search(
                    route.keywords or ["__FULL_QUERY__"],
                    full_query=user_question,
                    limit=max(memory_limit or 3, planner.min_results + 2),
                    thread_hint=None,
                    semantic_query=user_question,
                    query_variants=english_followup_variants,
                    scope_filters=scope_filters,
                )
                search_results = _merge_search_results(
                    search_results,
                    english_followup_results,
                    keep_order=preserve_retrieval_order,
                )
            if planner_model_plan is not None:
                for topic_hint in planner_model_plan.topic_hints:
                    topic_results = self.notetaker.fetch_records_by_topic(topic_hint, limit=max(memory_limit or 3, 3))
                    search_results = _merge_search_results(
                        search_results,
                        topic_results,
                        keep_order=preserve_retrieval_order,
                    )
                if planner_model_plan.recent_count > 0:
                    search_results = _merge_search_results(
                        search_results,
                        self.notetaker.fetch_recent_records(planner_model_plan.recent_count),
                        keep_order=preserve_retrieval_order,
                    )
            focus_score = max((_score_result_against_question_focus(user_question, item) for item in search_results[:6]), default=0)
            temporal_candidate_count = len(_extract_temporal_candidate_phrases(user_question)) if english_question else 0
            temporal_candidate_queries = _temporal_candidate_followup_queries(user_question) if english_question else []
            if temporal_candidate_queries and (
                temporal_candidate_count >= 2
                or len(search_results) < planner.min_results
                or focus_score <= 1
            ):
                retrieval_queries = _merge_strings(retrieval_queries, temporal_candidate_queries)
                for candidate_query in temporal_candidate_queries[:4]:
                    candidate_keywords = _extract_keywords_from_question(candidate_query) or ["__FULL_QUERY__"]
                    candidate_results = self.notetaker.search(
                        candidate_keywords,
                        full_query=candidate_query if "__FULL_QUERY__" in candidate_keywords else None,
                        limit=max(memory_limit or 3, 3),
                        thread_hint=None,
                        semantic_query=candidate_query,
                        query_variants=[candidate_query],
                        scope_filters=None,
                    )
                    candidate_results = [
                        item
                        for item in candidate_results
                        if _score_result_against_candidate(candidate_query, item) >= 4
                    ]
                    search_results = _merge_search_results(
                        search_results,
                        candidate_results,
                        keep_order=preserve_retrieval_order,
                    )
                focus_score = max((_score_result_against_question_focus(user_question, item) for item in search_results[:6]), default=0)
            if planner.active_date_scan and (len(search_results) < planner.min_results or focus_score <= 1):
                date_scan_hints = plan_temporal_date_hints(
                    scope_filters=scope_filters,
                    available_dates=self.notetaker.list_dates(),
                    limit=max(planner.min_results + 3, 6),
                )
                for date_value in date_scan_hints:
                    dated_results = self.notetaker.search(
                        route.keywords,
                        full_query=user_question if "__FULL_QUERY__" in route.keywords else None,
                        date_hint=date_value,
                        limit=memory_limit,
                        thread_hint=base_thread.thread_id,
                        semantic_query=user_question,
                        query_variants=effective_query_variants,
                        scope_filters=scope_filters,
                    )
                    search_results = _merge_search_results(
                        search_results,
                        dated_results,
                        keep_order=preserve_retrieval_order,
                    )
                    if len(search_results) >= planner.min_results:
                        break
            if planner.widen_search and len(search_results) < planner.min_results:
                widened_results = self.notetaker.search(
                    route.keywords,
                    full_query=user_question if "__FULL_QUERY__" in route.keywords else None,
                    limit=max(memory_limit or 3, planner.min_results + 2),
                    thread_hint=None,
                    semantic_query=user_question,
                    query_variants=effective_query_variants,
                    scope_filters=scope_filters,
                )
                search_results = _merge_search_results(
                    search_results,
                    widened_results,
                    keep_order=preserve_retrieval_order,
                )
            focus_limit = planner.memory_limit
            if temporal_candidate_count >= 2:
                focus_limit = max(focus_limit or 0, min(10, temporal_candidate_count * 3 + 2))
            search_results = focus_search_results(search_results, user_question, max_items=focus_limit)
            resolved_thread = derive_thread_context(user_question, route.keywords, search_results)
            planner = refine_planner_with_confusion(
                planner=planner,
                user_question=user_question,
                task_type=plan.task_type,
                search_results=search_results,
            )
            planner_steps = planner.steps
            if planner.confusion_level in {"medium", "high"} and plan.task_type == "grounded_answer":
                effective_executor_mode = "grounded_disambiguation"
                effective_executor_role = "reasoning"
                effective_collaboration_mode = planner.collaboration_mode
            evidence_thresholds = calculate_dynamic_threshold(
                user_question=user_question,
                plan=plan,
                planner=planner,
                search_results=search_results,
            )
            fact_sheet = self.notetaker.build_fact_sheet(
                search_results,
                question=user_question,
                evidence_thresholds=evidence_thresholds,
                scope_filters=scope_filters,
            )
            if english_question and hasattr(self.notetaker, "extract_english_memory_aids"):
                english_memory_aids = getattr(self.notetaker, "extract_english_memory_aids")(user_question, search_results)
                if english_memory_aids:
                    helper_lines = ["Granite helper worksheet:"]
                    if english_memory_aids.get("candidate_entities"):
                        helper_lines.append("- Candidate entities:")
                        helper_lines.extend(f"- {item}" for item in english_memory_aids["candidate_entities"][:8])
                    if english_memory_aids.get("numeric_candidates"):
                        helper_lines.append("- Candidate numbers:")
                        helper_lines.extend(f"- {item}" for item in english_memory_aids["numeric_candidates"][:8])
                    if english_memory_aids.get("atomic_facts"):
                        helper_lines.append("- Auxiliary atomic facts:")
                        helper_lines.extend(f"- {item}" for item in english_memory_aids["atomic_facts"][:8])
                    fact_sheet = f"{fact_sheet}\n\n" + "\n".join(helper_lines)
            evidence_assessment = assess_evidence_chain(
                user_question,
                search_results,
                evidence_thresholds=evidence_thresholds,
                contract_state=_slot_contract_state(user_question, search_results, fact_sheet),
            )
            if english_question and _should_start_coverage_loop(
                user_question,
                search_results,
                fact_sheet,
                evidence_assessment,
            ):
                while True:
                    slot_queries = [
                        str(query).strip()
                        for query in _slot_contract_state(user_question, search_results, fact_sheet).get("queries", [])
                        if str(query).strip()
                    ]
                    verifier_queries = list(slot_queries)
                    if planner_model_plan is not None:
                        verifier_queries = _merge_strings(verifier_queries, planner_model_plan.verification_focus)
                    if hasattr(self.notetaker, "build_english_followup_queries"):
                        verifier_queries = _merge_strings(
                            verifier_queries,
                            getattr(self.notetaker, "build_english_followup_queries")(user_question, search_results),
                        )
                    verifier_queries = _merge_strings(
                        verifier_queries,
                        _build_coverage_queries(user_question, search_results, scope_filters, fact_sheet),
                    )
                    verifier_queries = _merge_strings(verifier_queries, retrieval_queries)
                    if scope_filters.get("months"):
                        verifier_queries = _merge_strings(verifier_queries, scope_filters.get("months", []))
                    if scope_filters.get("locations"):
                        verifier_queries = _merge_strings(verifier_queries, scope_filters.get("locations", []))
                    verifier_queries = [
                        query
                        for query in verifier_queries
                        if query not in retrieval_queries or query == user_question
                    ][:10]
                    if not verifier_queries:
                        break
                    previous_result_count = len(search_results)
                    retrieval_iterations += 1
                    retrieval_queries = _merge_strings(retrieval_queries, verifier_queries)
                    verifier_results = self.notetaker.search(
                        route.keywords or ["__FULL_QUERY__"],
                        full_query=user_question,
                        limit=max(memory_limit or 3, planner.min_results + 4),
                        thread_hint=None,
                        semantic_query=user_question,
                        query_variants=verifier_queries,
                        scope_filters=scope_filters,
                    )
                    search_results = _merge_search_results(
                        search_results,
                        verifier_results,
                        keep_order=preserve_retrieval_order,
                    )
                    search_results = focus_search_results(search_results, user_question, max_items=planner.memory_limit)
                    evidence_thresholds = calculate_dynamic_threshold(
                        user_question=user_question,
                        plan=plan,
                        planner=planner,
                        search_results=search_results,
                    )
                    fact_sheet = self.notetaker.build_fact_sheet(
                        search_results,
                        question=user_question,
                        evidence_thresholds=evidence_thresholds,
                        scope_filters=scope_filters,
                    )
                    if english_question and hasattr(self.notetaker, "extract_english_memory_aids"):
                        english_memory_aids = getattr(self.notetaker, "extract_english_memory_aids")(user_question, search_results)
                        if english_memory_aids:
                            helper_lines = ["Granite helper worksheet:"]
                            if english_memory_aids.get("candidate_entities"):
                                helper_lines.append("- Candidate entities:")
                                helper_lines.extend(f"- {item}" for item in english_memory_aids["candidate_entities"][:8])
                            if english_memory_aids.get("numeric_candidates"):
                                helper_lines.append("- Candidate numbers:")
                                helper_lines.extend(f"- {item}" for item in english_memory_aids["numeric_candidates"][:8])
                            if english_memory_aids.get("atomic_facts"):
                                helper_lines.append("- Auxiliary atomic facts:")
                                helper_lines.extend(f"- {item}" for item in english_memory_aids["atomic_facts"][:8])
                            fact_sheet = f"{fact_sheet}\n\n" + "\n".join(helper_lines)
                    evidence_assessment = assess_evidence_chain(
                        user_question,
                        search_results,
                        evidence_thresholds=evidence_thresholds,
                        contract_state=_slot_contract_state(user_question, search_results, fact_sheet),
                    )
                    new_result_count = len(search_results) - previous_result_count
                    coverage_iterations.append(
                        {
                            "iteration": retrieval_iterations,
                            "queries": verifier_queries,
                            "new_result_count": new_result_count,
                            "signal_state": _coverage_signal_state(search_results),
                            "verifier_action": evidence_assessment.get("verifier_action") if evidence_assessment else None,
                        }
                    )
                    if not _should_continue_coverage_loop(
                        user_question,
                        search_results,
                        fact_sheet,
                        evidence_assessment,
                        retrieval_iterations,
                        new_result_count,
                    ):
                        break
            if (
                evidence_assessment is not None
                and evidence_assessment.get("verifier_action") == "verify"
                and effective_collaboration_mode == "off"
                and effective_executor_mode in {"grounded_answer", "grounded_disambiguation"}
            ):
                effective_collaboration_mode = "verify"
            if fact_sheet:
                reasoning_workspace = build_reasoning_workspace(
                    user_question,
                    fact_sheet,
                    planner_sub_tasks=planner_model_plan.sub_tasks if planner_model_plan else [],
                    planner_verification_focus=planner_model_plan.verification_focus if planner_model_plan else [],
                )
                reasoning_workspace_payload = reasoning_workspace.to_dict()
                fact_sheet = f"{fact_sheet}\n\n{reasoning_workspace.to_text()}"
            messages.append(
                make_message(
                    kind="memory_results",
                    source="notetaker",
                    target="orchestrator",
                    payload={
                        "result_count": len(search_results),
                        "results_preview": _search_result_preview(search_results),
                        "evidence_assessment": evidence_assessment,
                        "evidence_thresholds": evidence_thresholds,
                        "retrieval_iterations": retrieval_iterations,
                        "retrieval_queries": retrieval_queries[:8],
                        "coverage_iterations": coverage_iterations,
                        "reasoning_workspace": reasoning_workspace_payload,
                        "scope_filters": scope_filters,
                    },
                    thread_id=resolved_thread.thread_id,
                ).to_dict()
            )
            if log:
                if search_results:
                    print(f"[记事] 找到 {len(search_results)} 条相关记忆，线程={resolved_thread.label}")
                    print(f"[检索] 轮次={retrieval_iterations}, queries={retrieval_queries[:5]}")
                    if scope_filters.get("strict"):
                        print(f"[范围] {scope_filters}")
                    if evidence_assessment is not None:
                        print(
                            "[证据链] "
                            f"profile={(evidence_thresholds or {}).get('profile_name', 'default')}, "
                            f"confidence={evidence_assessment.get('level')}, "
                            f"verifier_action={evidence_assessment.get('verifier_action')}, "
                            f"reasons={evidence_assessment.get('reason_codes')}"
                        )
                else:
                    print("[记事] 未找到相关记忆")
            memory_heat = resolve_memory_heat(user_question, search_results)

        instruction_package = (
            self.planner_agent.build_instruction_package(
                user_question=user_question,
                task_type=effective_executor_mode,
                fact_sheet=fact_sheet,
                planner_strategy=planner.strategy,
                model_plan=planner_model_plan,
            )
            if self.planner_agent is not None
            else None
        )
        instruction_package_text = instruction_package.to_prompt() if instruction_package is not None else ""

        executor_target = self._resolve_executor_target(
            effective_executor_mode,
            user_question=user_question,
            use_memory=plan.use_memory,
            memory_heat=memory_heat,
            executor_role=effective_executor_role,
        )
        messages.append(
            make_message(
                kind="execution_request",
                source="orchestrator",
                target="executor",
                payload={
                    "mode": effective_executor_mode,
                    "executor_role": effective_executor_role,
                    "use_memory": plan.use_memory,
                    "allow_general_knowledge": plan.allow_general_knowledge,
                    "memory_heat": memory_heat,
                    "collaboration_mode": effective_collaboration_mode,
                    "instruction_package": instruction_package.to_dict() if instruction_package else None,
                    "executor_target": executor_target,
                    "evidence_assessment": evidence_assessment,
                    "evidence_thresholds": evidence_thresholds,
                },
                thread_id=resolved_thread.thread_id,
            ).to_dict()
        )

        answer = self.executor(
            user_question,
            fact_sheet,
            allow_general_knowledge=plan.allow_general_knowledge,
            task_type=effective_executor_mode,
            use_memory=plan.use_memory,
            memory_heat=memory_heat,
            executor_role=effective_executor_role,
            collaboration_mode=effective_collaboration_mode,
            instruction_package=instruction_package_text,
        )
        if log:
            preview = answer if len(answer) <= 80 else f"{answer[:77]}..."
            print(f"[执行] 回答: {preview}")
            print(f"[执行] 目标: {executor_target}")

        messages.append(
            make_message(
                kind="execution_result",
                source="executor",
                target="orchestrator",
                payload={
                    "mode": effective_executor_mode,
                    "executor_role": effective_executor_role,
                    "memory_heat": memory_heat,
                    "answer_preview": answer[:160],
                    "instruction_package": instruction_package.to_dict() if instruction_package else None,
                    "executor_target": executor_target,
                    "evidence_assessment": evidence_assessment,
                    "evidence_thresholds": evidence_thresholds,
                },
                thread_id=resolved_thread.thread_id,
            ).to_dict()
        )

        session_summary_after = (
            self.planner_agent.update_session_summary(
                user_question=user_question,
                answer=answer,
                instruction_package=instruction_package,
            )
            if self.planner_agent is not None
            else ""
        )
        summary = self.summarizer(user_question, answer)
        record_path = self.notetaker.write(
            user_query=user_question,
            assistant_response=answer,
            summary=summary,
            key_entities=_combine_entities(route, resolved_thread),
            thread_id=resolved_thread.thread_id,
            thread_label=resolved_thread.label,
            topic_tokens=resolved_thread.topic_tokens,
            metadata={
                "route_action": route.action,
                "executor_mode": effective_executor_mode,
                "executor_role": effective_executor_role,
                "collaboration_mode": effective_collaboration_mode,
                "memory_heat": memory_heat,
                "executor_target": executor_target,
                "memory_result_count": len(search_results),
                "retrieval_iterations": retrieval_iterations,
                "retrieval_queries": retrieval_queries[:8],
                "fact_sheet": fact_sheet,
                "evidence_layout": "gold_panning+dcr+sake" if fact_sheet else "",
                "planner": planner.to_dict(),
                "planner_model_plan": planner_model_plan.to_dict() if planner_model_plan else None,
                "instruction_package": instruction_package.to_dict() if instruction_package else None,
                "reasoning_workspace": reasoning_workspace_payload,
                "evidence_assessment": evidence_assessment,
                "evidence_thresholds": evidence_thresholds,
                "session_summary_before": session_summary_before,
                "session_summary_after": session_summary_after,
            },
        )
        messages.append(
            make_message(
                kind="memory_write",
                source="orchestrator",
                target="notetaker",
                payload={"record_path": record_path, "summary": summary},
                thread_id=resolved_thread.thread_id,
            ).to_dict()
        )
        if log:
            print(f"[记事] 本次对话已记录: {record_path}")

        return OrchestrationTrace(
            route=route,
            plan=plan,
            planner=planner,
            planner_steps=planner_steps,
            search_results=search_results,
            fact_sheet=fact_sheet,
            evidence_assessment=evidence_assessment,
            evidence_thresholds=evidence_thresholds,
            answer=answer,
            summary=summary,
            record_path=record_path,
            thread=resolved_thread,
            executor_target=executor_target,
            memory_heat=memory_heat,
            planner_model_plan=planner_model_plan.to_dict() if planner_model_plan else None,
            instruction_package=instruction_package.to_dict() if instruction_package else None,
            reasoning_workspace=reasoning_workspace_payload,
            retrieval_iterations=retrieval_iterations,
            retrieval_queries=retrieval_queries[:8],
            session_summary_before=session_summary_before,
            session_summary_after=session_summary_after,
            messages=messages,
        )

    def run(self, user_question: str, log: bool = True) -> str:
        return self.run_with_trace(user_question, log=log).answer
