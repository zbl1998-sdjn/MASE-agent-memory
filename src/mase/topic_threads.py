"""主题线程推断工具，用于把问题、关键词和检索结果绑定到稳定 thread。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

THREAD_CONCEPT_MAP = {
    "API网关": ["网关", "端口", "灰度入口", "gateway"],
    "Q3预算": ["预算", "营销预算", "线上投放", "效果广告", "短视频种草"],
    "仓储迁移": ["仓储迁移", "迁移项目", "灰度切换", "星河-7"],
    "客服质检": ["语音质检", "质检", "供应商", "高风险样本"],
    "复盘会": ["复盘会", "会议室", "跨部门复盘"],
    "退款预警": ["退款预警阈值", "人工复审", "风控", "退款预警"],
    "RAG": ["RAG", "长上下文", "检索", "回忆稳定性"],
}

RECALL_MARKERS = (
    "之前",
    "上次",
    "刚才",
    "前面",
    "最开始",
    "还记得",
    "说过",
    "聊到",
    "讨论过",
    "记录",
    "记住",
    "确认过",
)

ENGLISH_RECALL_MARKERS = (
    "before",
    "earlier",
    "previously",
    "last time",
    "remember",
    "you mentioned",
    "we discussed",
    "we talked about",
    "recorded",
    "noted",
)

THREAD_STOPWORDS = {
    "请记住",
    "记住",
    "帮我",
    "我们",
    "之前",
    "上次",
    "刚才",
    "前面",
    "最开始",
    "那个",
    "这个",
    "一下",
    "什么",
    "多少",
    "怎么",
    "如果",
    "请把",
    "告诉我",
    "再说一遍",
    "再确认一下",
}

ENGLISH_THREAD_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "last",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "please",
    "remember",
    "said",
    "tell",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "to",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
    "your",
}


@dataclass(frozen=True)
class ThreadContext:
    """一次对话/检索归属的主题线程上下文。"""

    thread_id: str
    label: str
    topic_tokens: list[str]
    confidence: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "label": self.label,
            "topic_tokens": self.topic_tokens,
            "confidence": self.confidence,
            "source": self.source,
        }


def detect_text_language(text: str) -> str:
    """用轻量字符比例判断文本主语言。"""
    sample = str(text or "").strip()
    if not sample:
        return "zh"
    ascii_letters = len(re.findall(r"[A-Za-z]", sample))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", sample))
    if ascii_letters >= 6 and ascii_letters > chinese_chars * 2:
        return "en"
    return "zh"


def _contains_any(text: str, fragments: tuple[str, ...]) -> bool:
    """大小写不敏感地检查片段命中。"""
    lowered = str(text or "").lower()
    return any(fragment.lower() in lowered for fragment in fragments)


def _unique(items: list[str]) -> list[str]:
    """保持原顺序去重。"""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(item)
    return result


def _extract_terms(text: str) -> list[str]:
    """从问题文本中抽取主题候选词。"""
    if not text.strip():
        return []

    extracted: list[str] = []
    lowered = text.lower()
    for canonical, aliases in THREAD_CONCEPT_MAP.items():
        # 先用领域概念表把别名收敛到规范主题名。
        variants = [canonical, *aliases]
        if any(variant.lower() in lowered for variant in variants):
            extracted.append(canonical)

    if detect_text_language(text) == "en":
        # 英文路径保留专名大小写，同时过滤常见功能词。
        word_matches = re.findall(r"[A-Za-z][A-Za-z0-9\-']*", text)
        for raw_word in word_matches:
            normalized = re.sub(r"'s$", "", raw_word.strip(" -'")).lower()
            if len(normalized) < 3:
                continue
            if normalized in ENGLISH_THREAD_STOPWORDS:
                continue
            extracted.append(raw_word if raw_word[:1].isupper() else normalized)

        phrase_matches = re.findall(r"\b(?:[A-Za-z][A-Za-z0-9\-']*\s+){1,2}[A-Za-z][A-Za-z0-9\-']*\b", text)
        for phrase in phrase_matches:
            # 2-3 词短语比单词更适合做 thread label，但首尾不能是停用词。
            words = re.findall(r"[A-Za-z][A-Za-z0-9\-']*", phrase)
            normalized_words = [
                re.sub(r"'s$", "", word.strip(" -'")).lower()
                for word in words
                if re.sub(r"'s$", "", word.strip(" -'")).lower() not in ENGLISH_THREAD_STOPWORDS
            ]
            if len(normalized_words) < 2:
                continue
            if normalized_words[0] in ENGLISH_THREAD_STOPWORDS or normalized_words[-1] in ENGLISH_THREAD_STOPWORDS:
                continue
            extracted.append(" ".join(normalized_words))
    else:
        # 中文路径直接抽取连续 CJK 片段和少量英文/数字配置项。
        fragments = re.findall(r"[A-Za-z0-9\-]+|[\u4e00-\u9fff]{2,12}", text)
        for fragment in fragments:
            normalized = fragment.strip("，。！？、：；,.!? ").strip()
            if len(normalized) < 2:
                continue
            if normalized in THREAD_STOPWORDS:
                continue
            extracted.append(normalized)

    filtered = []
    for item in _unique(extracted):
        if item in THREAD_STOPWORDS:
            continue
        filtered.append(item)
    return filtered[:6]


def _record_thread_context(record: dict[str, Any]) -> ThreadContext | None:
    """从搜索结果行中恢复已记录的 thread 上下文。"""
    thread_id = str(record.get("thread_id") or "").strip()
    if not thread_id:
        return None
    label = str(record.get("thread_label") or "").strip() or "未命名线程"
    raw_topic_tokens = record.get("topic_tokens")
    if raw_topic_tokens is None:
        topic_tokens = []
    elif isinstance(raw_topic_tokens, str):
        text = raw_topic_tokens.strip()
        if not text:
            topic_tokens = []
        elif text.startswith("["):
            # SQLite/JSON 两种历史写法都兼容，解析失败时按逗号切分。
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                topic_tokens = [item.strip() for item in text.split(",") if item.strip()]
            else:
                topic_tokens = [str(item).strip() for item in parsed if str(item).strip()]
        else:
            topic_tokens = [item.strip() for item in text.split(",") if item.strip()]
    else:
        topic_tokens = [str(item).strip() for item in raw_topic_tokens if str(item).strip()]
    return ThreadContext(
        thread_id=thread_id,
        label=label,
        topic_tokens=topic_tokens,
        confidence=0.95,
        source="memory_record",
    )


def _build_thread_id(tokens: list[str]) -> str:
    """用主题 token 的稳定哈希生成 thread_id。"""
    seed = " | ".join(tokens[:4]) if tokens else "general"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"thread-{digest}"


def derive_thread_context(
    user_question: str,
    route_keywords: list[str] | None = None,
    search_results: list[dict[str, Any]] | None = None,
) -> ThreadContext:
    """综合问题、Router 关键词和搜索结果推断当前主题线程。"""
    route_keywords = route_keywords or []
    search_results = search_results or []

    recall_like = _contains_any(user_question, RECALL_MARKERS + ENGLISH_RECALL_MARKERS)
    question_terms = _extract_terms(user_question)
    route_terms = [keyword for keyword in route_keywords if keyword and keyword != "__FULL_QUERY__"]
    candidate_terms = _unique(route_terms + question_terms)

    if search_results:
        for result in search_results:
            record_thread = _record_thread_context(result)
            if record_thread is None:
                continue
            if recall_like:
                # 明确回忆类问题优先沿用命中的历史 thread。
                return record_thread
            if candidate_terms:
                overlap = set(token.lower() for token in candidate_terms) & set(
                    token.lower() for token in record_thread.topic_tokens
                )
                if overlap:
                    # 非回忆类问题只有主题 token 重叠时才复用历史 thread，避免误归档。
                    return record_thread

    if not candidate_terms and search_results:
        fallback_thread = _record_thread_context(search_results[0])
        if fallback_thread is not None:
            # 没有可用候选词时，第一条检索结果提供最保守的线程归属。
            return fallback_thread

    if not candidate_terms:
        candidate_terms = ["通用对话"]

    label = " / ".join(candidate_terms[:2])
    # 置信度体现来源强弱：Router 关键词 > 问题抽词 > 通用兜底。
    confidence = 0.88 if route_terms else 0.72 if question_terms else 0.55
    return ThreadContext(
        thread_id=_build_thread_id(candidate_terms),
        label=label,
        topic_tokens=candidate_terms[:4],
        confidence=confidence,
        source="question_inference",
    )
