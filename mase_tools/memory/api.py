from typing import Any

from .correction_detector import (
    CorrectionSignal,
    detect_correction,
    extract_keywords_for_supersede,
)
from .db_core import (
    add_event_log,
    archive_entity_fact,
    consolidate_thread,
    delete_session_context,
    facts_first_recall,
    gc_expired_session_context,
    get_entity_fact_history,
    get_entity_facts,
    get_session_context,
    list_episodic_snapshots,
    list_procedures,
    register_procedure,
    search_entity_facts_by_keyword,
    supersede_log_entries,
    upsert_entity_fact,
    upsert_session_context,
)


def mase2_write_interaction(
    thread_id: str,
    role: str,
    content: str,
    *,
    scope_filters: dict[str, Any] | None = None,
) -> str:
    """写入基础的对话流水账"""
    scope = dict(scope_filters or {})
    log_id = add_event_log(thread_id, role, content, **scope)
    return f"Success: Event logged with ID {log_id}"

def mase2_upsert_fact(
    category: str,
    key: str,
    value: str,
    *,
    reason: str | None = None,
    source_log_id: int | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> str:
    """写入提取出的实体状态 (Entity Fact)"""
    upsert_entity_fact(
        category,
        key,
        value,
        reason=reason,
        source_log_id=source_log_id,
        **dict(scope_filters or {}),
    )
    return f"Success: Fact {category}.{key} updated to {value}"

def mase2_search_memory(keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
    """Facts-first unified recall: entity_state current facts first, then BM25 event-log.

    Replaces the previous event-log-only implementation. Signature is backward-
    compatible (same positional args, same return type). Callers that need the
    raw event-log only should use ``search_event_log`` directly.
    """
    return facts_first_recall(keywords, limit=limit)

def mase2_get_facts(category: str = None, *, scope_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """获取所有/特定的实体状态字典，这应该作为高优先级上下文"""
    return get_entity_facts(category, **dict(scope_filters or {}))


# ---------- Auto-correction (Mem0-style UPDATE/DELETE) ----------

def mase2_detect_correction(utterance: str) -> CorrectionSignal:
    """检测一句用户话语是否包含"我之前说错了/actually..." 类纠正触发词。"""
    return detect_correction(utterance)


def mase2_supersede_facts(
    keywords: list[str],
    replacement_log_id: int,
    reason: str = "user_correction",
) -> dict[str, Any]:
    """把所有命中 ``keywords`` 的旧流水账标记为 superseded，新值由 replacement_log_id 指向。

    返回 {"superseded_count": N}.
    """
    n = supersede_log_entries(keywords, replacement_log_id, reason=reason)
    return {"superseded_count": n, "replacement_log_id": replacement_log_id, "reason": reason}


def mase2_correct_and_log(
    thread_id: str,
    new_utterance: str,
    *,
    role: str = "user",
    extra_keywords: list[str] | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """端到端 helper：写入新的 utterance，并自动 supersede 旧的同主题流水账。

    1. ``add_event_log`` 写入新行 → 拿到 ``new_log_id``
    2. ``detect_correction`` 判断是否为纠正
    3. 若是 → ``extract_keywords_for_supersede`` 抽取主题词 → ``supersede_log_entries``

    无论是否触发 supersede，都返回 ``new_log_id``，调用方拿来后续 upsert_fact 时
    传入 source_log_id，形成"事实变化 ⇄ 触发对话"双向溯源。
    """
    scope = dict(scope_filters or {})
    new_id = add_event_log(thread_id, role, new_utterance, **scope)
    signal = detect_correction(new_utterance)
    result: dict[str, Any] = {
        "new_log_id": new_id,
        "is_correction": bool(signal),
        "matched_pattern": signal.matched_pattern,
        "superseded_count": 0,
    }
    if signal:
        kws = extract_keywords_for_supersede(new_utterance)
        if extra_keywords:
            kws = list(dict.fromkeys([*kws, *extra_keywords]))
        if kws:
            n = supersede_log_entries(kws, new_id, reason="user_correction", **scope)
            result["superseded_count"] = n
            result["matched_keywords"] = kws
    return result


def mase2_get_fact_history(
    category: str | None = None,
    entity_key: str | None = None,
    limit: int = 50,
    *,
    scope_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """查询事实审计链 (Mem0 缺乏的能力)。"""
    return get_entity_fact_history(
        category=category,
        entity_key=entity_key,
        limit=limit,
        **dict(scope_filters or {}),
    )


def mase2_search_entity_facts(
    keywords: list[str],
    limit: int = 20,
    *,
    scope_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keyword search over entity_state facts. Results carry ``_source='entity_state'``."""
    return search_entity_facts_by_keyword(keywords, limit=limit, **dict(scope_filters or {}))


def mase2_facts_first_recall(
    keywords: list[str],
    *,
    full_query: str | None = None,
    limit: int = 5,
    include_history: bool = False,
    scope_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Facts-first unified recall: entity_state current facts first, then session log evidence.

    Every result carries ``_source`` ('entity_state' or 'memory_log') for
    audit/source visibility in downstream fact-sheet builders.
    """
    return facts_first_recall(
        keywords,
        full_query=full_query,
        limit=limit,
        include_history=include_history,
        **dict(scope_filters or {}),
    )


def mase2_upsert_session_context(
    session_id: str,
    context_key: str,
    context_value: str,
    *,
    ttl_days: int | None = None,
    metadata: dict[str, Any] | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scope = dict(scope_filters or {})
    upsert_session_context(
        session_id,
        context_key,
        context_value,
        ttl_days=ttl_days,
        metadata=metadata,
        **scope,
    )
    return {"session_id": session_id, "context_key": context_key, "updated": True}


def mase2_get_session_context(
    session_id: str,
    *,
    include_expired: bool = False,
    scope_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return get_session_context(session_id, include_expired=include_expired, **dict(scope_filters or {}))


def mase2_register_procedure(
    procedure_key: str,
    content: str,
    *,
    procedure_type: str = "rule",
    metadata: dict[str, Any] | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    register_procedure(
        procedure_key,
        content,
        procedure_type=procedure_type,
        metadata=metadata,
        **dict(scope_filters or {}),
    )
    return {"procedure_key": procedure_key, "procedure_type": procedure_type, "updated": True}


def mase2_list_procedures(
    procedure_type: str | None = None,
    *,
    scope_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return list_procedures(procedure_type=procedure_type, **dict(scope_filters or {}))


def mase2_consolidate_session(
    thread_id: str,
    *,
    max_items: int = 50,
    scope_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return consolidate_thread(thread_id, max_items=max_items, **dict(scope_filters or {}))


def mase2_list_episodic_snapshots(
    thread_id: str | None = None,
    *,
    scope_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return list_episodic_snapshots(thread_id=thread_id, **dict(scope_filters or {}))


def mase2_forget_fact(
    category: str,
    entity_key: str,
    *,
    scope_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"archived_count": archive_entity_fact(category, entity_key, **dict(scope_filters or {}))}


def mase2_forget_session_context(
    session_id: str,
    *,
    context_key: str | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "deleted_count": delete_session_context(
            session_id,
            context_key=context_key,
            **dict(scope_filters or {}),
        )
    }


def mase2_gc_session_context() -> dict[str, Any]:
    return {"deleted_count": gc_expired_session_context()}
