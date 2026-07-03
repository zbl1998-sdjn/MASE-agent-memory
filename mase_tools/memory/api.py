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
from .media_records import (
    get_media_provenance,
    record_extraction,
    register_media_asset,
)


def mase2_write_interaction(
    thread_id: str,
    role: str,
    content: str,
    *,
    source_media_id: int | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> str:
    """写入基础的对话流水账"""
    scope = dict(scope_filters or {})
    log_id = add_event_log(thread_id, role, content, source_media_id=source_media_id, **scope)
    return f"Success: Event logged with ID {log_id}"

def mase2_upsert_fact(
    category: str,
    key: str,
    value: str,
    *,
    reason: str | None = None,
    source_log_id: int | None = None,
    source_media_id: int | None = None,
    scope_filters: dict[str, Any] | None = None,
    evidence_text: str | None = None,
    evidence_source_type: str | None = None,
    evidence_source_id: str | None = None,
    evidence_trust_level: int | None = None,
    evidence_full_text: str | None = None,
) -> str:
    """写入提取出的实体状态 (Entity Fact)。

    evidence_* 五个可选参数给齐时,额外双写治理层 facts(P0):evidence_text
    须能在 evidence_full_text 中机械定位,否则 quarantined。旧调用方(不传
    evidence)行为零变化;治理层失败不阻塞 entity_state 写入,失败信息附在
    返回消息里留痕。
    """
    upsert_entity_fact(
        category,
        key,
        value,
        reason=reason,
        source_log_id=source_log_id,
        source_media_id=source_media_id,
        **dict(scope_filters or {}),
    )
    message = f"Success: Fact {category}.{key} updated to {value}"
    if None not in (
        evidence_text, evidence_source_type, evidence_source_id,
        evidence_trust_level, evidence_full_text,
    ):
        try:
            from mase.governance.fact_contract import (  # noqa: PLC0415
                ClaimType,
                FactContract,
                new_fact_id,
                utc_now,
            )
            from mase.governance.fact_store import propose_fact  # noqa: PLC0415

            filters = dict(scope_filters or {})
            propose_fact(
                FactContract(
                    fact_id=new_fact_id(),
                    entity_id="user:default",
                    claim_type=ClaimType.PROJECT_FACT,
                    subject=category,
                    predicate=key,
                    object_value=value,
                    # 门面路径无自报置信度,取 1.0 并如实标注未标定。
                    confidence=1.0,
                    observed_at=utc_now(),
                    confidence_basis={
                        "method": "mechanical_span_bind",
                        "producer": "mase2_upsert_fact",
                        "calibrated": False,
                    },
                    tenant_id=str(filters.get("tenant_id") or ""),
                    workspace_id=str(filters.get("workspace_id") or ""),
                ),
                str(evidence_text),
                source_type=str(evidence_source_type),
                source_id=str(evidence_source_id),
                trust_level=int(evidence_trust_level or 0),
                source_full_text=str(evidence_full_text),
            )
        except Exception as exc:  # noqa: BLE001 — 治理层 best-effort,失败留痕不阻塞
            message += f" (governance_dual_write_failed: {type(exc).__name__}: {exc})"
    return message

def mase2_compile_evidence_pack(
    question: str,
    keywords: list[str],
    *,
    entity_id: str | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    """编译治理层 Evidence Pack(P2):dict 含五节内容 + markdown 渲染。

    面向新读路径的接缝;不触碰 mase2_search_memory 既有行为。检索与编译
    审计自动落 retrieval_runs / context_packs,可回放。
    """
    from mase.governance.evidence_pack import (  # noqa: PLC0415
        compile_evidence_pack,
        render_markdown,
    )

    pack = compile_evidence_pack(question, keywords, entity_id=entity_id, top_k=top_k)
    result = pack.to_dict()
    result["markdown"] = render_markdown(pack)
    return result


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


# ---------- Multimodal provenance (S0) ----------

def mase2_register_media_asset(
    sha256: str,
    *,
    source_uri: str | None,
    media_type: str,
    byte_size: int | None = None,
    page_count: int | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> int:
    """登记媒体资产(内容寻址,幂等),返回 media_id。"""
    return register_media_asset(
        sha256,
        source_uri=source_uri,
        media_type=media_type,
        byte_size=byte_size,
        page_count=page_count,
        **dict(scope_filters or {}),
    )


def mase2_record_extraction(
    media_id: int,
    *,
    extractor_name: str,
    model_name: str,
    extractor_version: str,
    full_text: str,
    result_json: str,
    scope_filters: dict[str, Any] | None = None,
) -> int:
    """落一条可审计抽取记录,返回 extraction_id。"""
    return record_extraction(
        media_id,
        extractor_name=extractor_name,
        model_name=model_name,
        extractor_version=extractor_version,
        full_text=full_text,
        result_json=result_json,
        **dict(scope_filters or {}),
    )


def mase2_get_media_provenance(media_id: int) -> dict[str, Any]:
    """读取媒体溯源链:资产 + 抽取记录列表。"""
    return get_media_provenance(media_id)
