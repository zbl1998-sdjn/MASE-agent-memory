"""Candidate-table builders for long-context disambiguation."""
from __future__ import annotations

import re
from typing import Any

from .fact_sheet_common import extract_focused_window, strip_memory_prefixes

_EN_CANDIDATE_STOPWORDS = {
    "user",
    "assistant",
    "summary",
    "entities",
    "question",
    "answer",
    "cannot answer",
}

_CJK_NAME_STOPWORDS = {
    "基准历史",
    "事实备忘",
    "候选证据",
    "现代物理",
    "现代物理学",
    "物理学",
    "科学家",
    "奠基人",
    "奠基者",
    "今日现代",
    "意大利",
    "日心说",
    "相对论",
    "量子力学",
    "诺贝尔",
    "声名",
    "声名播",
    "影响深远",
    "原来",
    "但真",
    "但只",
    "知道",
    "此一发现",
    "莫不",
}


def _candidate_query_tokens(user_question: str) -> list[str]:
    stopwords = {
        "what",
        "which",
        "whose",
        "name",
        "the",
        "is",
        "of",
        "as",
    }
    tokens = re.findall(r"[A-Za-z][A-Za-z\-']{2,}", user_question)
    return [token.lower() for token in tokens if token.lower() not in stopwords]


def _candidate_query_tokens_cjk(user_question: str) -> list[str]:
    stop_fragments = {
        "什么",
        "名字",
        "叫什",
        "叫做",
        "哪位",
        "哪个",
        "哪一",
        "多少",
        "为何",
        "为什么",
        "请问",
    }
    tokens: list[str] = []
    seen: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]{3,}", user_question):
        for size in range(min(8, len(run)), 1, -1):
            for index in range(0, len(run) - size + 1):
                token = run[index : index + size]
                if any(fragment in token for fragment in stop_fragments):
                    continue
                if token in seen:
                    continue
                seen.add(token)
                tokens.append(token)
    return sorted(tokens, key=lambda item: (-len(item), item))[:160]


def _extract_english_name_candidates(text: str) -> list[str]:
    matches = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b", text)
    deduped: list[str] = []
    seen: set[str] = set()
    for match in matches:
        lowered = match.lower()
        if lowered in _EN_CANDIDATE_STOPWORDS or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(match)
    return deduped


def _normalize_cjk_candidate_name(name: str) -> str:
    candidate = re.sub(r"^(?:这位|那位|一个|一代|某位)", "", str(name or "").strip())
    candidate = re.sub(r"(?:先生|女士|博士|教授|学士)$", "", candidate)
    candidate = candidate.strip(" ，,。；;：:\"“”‘’（）()[]【】")
    if not (2 <= len(candidate) <= 8):
        return ""
    if not all("\u4e00" <= char <= "\u9fff" for char in candidate):
        return ""
    if candidate in _CJK_NAME_STOPWORDS:
        return ""
    if "的" in candidate:
        return ""
    if candidate.startswith(("这", "那", "此", "其", "彼", "若", "但", "莫")):
        return ""
    if any(candidate.endswith(suffix) for suffix in ("历史", "年间", "物理", "理论", "学术", "研究", "贡献", "方法")):
        return ""
    if any(candidate.endswith(suffix) for suffix in ("发现", "深远", "声名", "救兵", "猴子", "妖怪", "妖精")):
        return ""
    return candidate


def _extract_cjk_name_candidates(text: str) -> list[str]:
    patterns = (
        r"(?:^|[。！？；;：:\n，,]\s*)([\u4e00-\u9fff]{2,8}?)(?:先生|女士|博士|教授|学士)?(?:，|,)?(?:乃为|乃一|乃|是|为|被|作为|研究于)",
        r"([\u4e00-\u9fff]{2,8}?)(?:先生|女士|博士|教授|学士)?(?:乃为|乃一|亦对|被誉为|被称为|研究于)",
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for raw in re.findall(pattern, text):
            name = _normalize_cjk_candidate_name(raw)
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(name)
    return deduped


def _earliest_query_anchor(text: str, query_tokens: list[str]) -> int:
    lowered = text.lower()
    positions = [lowered.find(token) for token in query_tokens if token and lowered.find(token) >= 0]
    return min(positions) if positions else -1


def _nearest_preceding_cjk_name(text: str, anchor_index: int) -> str:
    if anchor_index < 0:
        return ""
    start = max(0, anchor_index - 420)
    prefix = text[start:anchor_index]
    names = _extract_cjk_name_candidates(prefix)
    return names[-1] if names else ""


def _nearest_preceding_name(text: str, anchor_index: int) -> str:
    if anchor_index < 0:
        return ""
    start = max(0, anchor_index - 360)
    prefix = text[start:anchor_index]
    names = _extract_english_name_candidates(prefix)
    return names[-1] if names else ""


def _candidate_evidence_snippet(content: str, candidate_name: str, anchor_index: int, fallback_snippet: str) -> str:
    lowered = content.lower()
    candidate_lower = candidate_name.lower()
    name_index = lowered.rfind(candidate_lower, 0, anchor_index if anchor_index > 0 else len(content))
    if name_index < 0:
        return fallback_snippet
    start = max(0, name_index - 40)
    end = min(len(content), max(anchor_index + 220, name_index + len(candidate_name) + 220))
    snippet = " ".join(content[start:end].split())
    if start > 0:
        snippet = "…" + snippet
    if end < len(content):
        snippet = snippet + "…"
    return snippet


def _build_candidate_table(
    user_question: str,
    search_results: list[dict[str, Any]],
    terms_sorted: list[str],
) -> list[str]:
    lowered_question = user_question.lower()
    if not any(marker in lowered_question for marker in ("who", "which", "what is the name", "what's the name")):
        return []
    query_tokens = _candidate_query_tokens(user_question)
    candidate_rows: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for item in search_results[:8]:
        content = strip_memory_prefixes(str(item.get("content") or "").strip())
        if not content:
            continue
        anchor_index = _earliest_query_anchor(content, query_tokens)
        snippet = extract_focused_window(
            content,
            terms_sorted or query_tokens,
            radius=180,
            max_windows=1,
        )
        lowered_content = content.lower()
        hit_count = sum(1 for token in query_tokens if token in lowered_content)
        if query_tokens and hit_count < 1:
            continue
        candidate_names = _extract_english_name_candidates(snippet)
        preceding_name = _nearest_preceding_name(content, anchor_index)
        if preceding_name:
            candidate_names = [preceding_name, *candidate_names]
        for name in candidate_names:
            key = name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            evidence = _candidate_evidence_snippet(content, name, anchor_index, snippet)
            candidate_rows.append((name, evidence))
            break
        if len(candidate_rows) >= 4:
            break
    if len(candidate_rows) < 2:
        return []
    lines = [
        "Candidate table: compare the named candidates below before answering. Prefer the candidate best supported by the retrieved evidence, not the most world-plausible one."
    ]
    for index, (name, snippet) in enumerate(candidate_rows, start=1):
        lines.append(f"[C{index}] name={name} | evidence={snippet}")
    return lines


def _build_cjk_candidate_table(
    user_question: str,
    search_results: list[dict[str, Any]],
    terms_sorted: list[str],
) -> list[str]:
    if not any(marker in user_question for marker in ("叫什么名字", "叫做什么", "哪位", "何人", "是谁", "谁")):
        return []
    query_tokens = _candidate_query_tokens_cjk(user_question)
    if not query_tokens:
        return []
    candidate_rows: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for item in search_results[:8]:
        content = strip_memory_prefixes(str(item.get("content") or "").strip())
        if not content:
            continue
        lowered_content = content.lower()
        hit_count = sum(1 for token in query_tokens if token.lower() in lowered_content)
        if hit_count < 1:
            continue
        anchor_index = _earliest_query_anchor(content, query_tokens)
        snippet = extract_focused_window(
            content,
            terms_sorted or query_tokens,
            radius=180,
            max_windows=1,
        )
        candidate_names = _extract_cjk_name_candidates(snippet)
        preceding_name = _nearest_preceding_cjk_name(content, anchor_index)
        if preceding_name:
            candidate_names = [preceding_name, *candidate_names]
        for name in candidate_names:
            if name in seen_names:
                continue
            seen_names.add(name)
            evidence = _candidate_evidence_snippet(content, name, anchor_index, snippet)
            candidate_rows.append((name, evidence))
            break
        if len(candidate_rows) >= 4:
            break
    if not candidate_rows:
        return []
    lines = [
        "候选裁决表：回答前必须逐项比较下面的候选名。优先选择检索证据中与问题关键词共同出现、且最受原文支持的候选；不要按常识猜。"
    ]
    for index, (name, snippet) in enumerate(candidate_rows, start=1):
        lines.append(f"[C{index}] name={name} | evidence={snippet}")
    return lines


__all__ = ["_build_candidate_table", "_build_cjk_candidate_table"]
