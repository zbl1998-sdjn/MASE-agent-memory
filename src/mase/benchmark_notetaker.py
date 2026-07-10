"""Benchmark runner 使用的 SQLite 版 `BenchmarkNotetaker`。

两阶段召回：先用 FTS5 BM25 收集候选，再在 Python 侧做共现/密度重排，并用
子串匹配兜底。这样即使 FTS 漏掉部分词或模糊词，召回率也不会明显下降。

Facts-first 召回：底层 DB 存在 ``entity_state`` 表时（通过 ``MASE_DB_PATH``
共享或自动创建），``search()`` 会把当前实体事实放在会话/event-log 证据之前。
每条结果都带 ``_source``（entity_state 或 memory_log），便于审计。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mase_tools.memory.db_core import (
    add_memory_log,
    fetch_memory_rows,
    get_connection,
    init_db,
    resolve_db_path,
    search_entity_fact_history_by_keyword,
    search_entity_facts_by_keyword,
)

try:
    from mase_tools.memory import tri_vault as _tri_vault  # 可选磁盘镜像。
except ImportError:  # pragma: no cover — 包布局回退。
    _tri_vault = None  # type: ignore[assignment]


class BenchmarkNotetaker:
    """benchmark runner 使用的按运行隔离 SQLite 记忆实现。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.db_path = resolve_db_path(config_path)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """产出带事务保护的 SQLite 连接，并保证退出时关闭。

        旧实现直接返回 Connection，调用方写成 ``with self._connect() as conn:``。
        但 Python 的 ``sqlite3`` 连接上下文只负责 commit/rollback，不负责
        ``close()``。长时间 benchmark 中，每次 write/search/_init_db 都会泄漏
        文件句柄，最终在 Windows 上触发 ``OSError [Errno 24]``。

        现在所有调用点仍保留原 idiom，但连接会确定性关闭，同时保留事务语义。
        """
        conn = get_connection(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        init_db(self.db_path)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'"
            ).fetchone()
        self._fts_enabled = row is not None

    def _search_entity_state(
        self,
        terms: list[str],
        *,
        limit: int,
        scope_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """查询当前实体事实，作为 facts-first 召回的第一层。"""
        if not terms:
            return []
        scope = dict(scope_filters or {})
        return search_entity_facts_by_keyword(
            terms,
            limit=limit,
            db_path=self.db_path,
            tenant_id=scope.get("tenant_id"),
            workspace_id=scope.get("workspace_id"),
            visibility=scope.get("visibility"),
        )

    def _extract_terms(self, keywords: list[str], full_query: str | None = None, query_variants: list[str] | None = None) -> list[str]:
        """从关键词、全文问题和查询变体中扩展可检索术语。"""
        raw_terms = [str(item or "").strip() for item in [*(keywords or []), *(query_variants or [])] if str(item or "").strip()]
        if "__FULL_QUERY__" in raw_terms:
            # FULL_QUERY 哨兵代表搜索层应使用原问题，而不是把哨兵当作字面关键词。
            raw_terms = [term for term in raw_terms if term != "__FULL_QUERY__"]
            raw_terms.append(str(full_query or "").strip())
        if full_query and not raw_terms:
            raw_terms.append(str(full_query).strip())
        expanded: list[str] = []
        for term in raw_terms:
            expanded.append(term)
            english_words = re.findall(r"[A-Za-z][A-Za-z0-9_\-']{2,}", term)
            expanded.extend(english_words)
            expanded.extend(re.findall(r"[\u4e00-\u9fff]{2,16}", term))
            # 轻量英文词干前缀：让 physics 命中 physicist，scientist 命中
            # scientists/scientific，modern 命中 modernity。只对较长内容词剥掉
            # 2-3 个尾字符，阈值保守，避免 LME 中 today/yesterday/thinking 等常见词
            # 过度扩展后把无关轮次排到相关轮次前面。
            STEM_STOPWORDS = {
                "today", "yesterday", "tomorrow", "thinking", "remember",
                "remembered", "remembering", "would", "should", "could",
                "really", "anything", "something", "everything", "nothing",
                "because", "before", "after", "always", "never", "between",
                "another", "without", "during", "around", "myself", "yourself",
                "themselves", "actually", "probably", "definitely",
                "morning", "evening", "afternoon", "weekend", "weekday",
                "started", "finished", "thought", "looking", "trying",
                "working", "talking", "playing", "watching", "reading",
            }
            for word in english_words:
                wl = word.lower()
                if len(word) >= 7 and "-" not in word and "'" not in word and wl not in STEM_STOPWORDS:
                    stem2 = word[:-2]
                    if len(stem2) >= 5:
                        expanded.append(stem2)
                    if len(word) >= 9:
                        stem3 = word[:-3]
                        if len(stem3) >= 6:
                            expanded.append(stem3)
            chinese_runs = re.findall(r"[\u4e00-\u9fff]{4,}", term)
            for run in chinese_runs:
                # 中文长片段拆成 2/3/4-gram，弥补 FTS 对 CJK 边界不敏感的问题。
                for size in (2, 3, 4):
                    if len(run) < size:
                        continue
                    expanded.extend(run[index : index + size] for index in range(0, len(run) - size + 1))
        deduped: list[str] = []
        seen: set[str] = set()
        for term in expanded:
            normalized = term.strip()
            if len(normalized) < 2:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(normalized)
        return deduped

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
    ) -> str:
        """写入一条 benchmark 记忆日志，并可选镜像到 tri-vault。"""
        content_parts = [
            f"User: {user_query.strip()}" if str(user_query or "").strip() else "",
            f"Assistant: {assistant_response.strip()}" if str(assistant_response or "").strip() else "",
        ]
        if summary.strip():
            content_parts.append(f"Summary: {summary.strip()}")
        if key_entities:
            content_parts.append("Entities: " + ", ".join(str(item) for item in key_entities if str(item).strip()))
        content = "\n".join(part for part in content_parts if part)
        row_id = add_memory_log(
            thread_id or "default",
            "assistant" if str(assistant_response or "").strip() else "user",
            content or str(user_query or "").strip(),
            thread_label=thread_label or "",
            summary=summary or "",
            topic_tokens=json.dumps(topic_tokens or [], ensure_ascii=False),
            metadata=json.dumps(metadata or {}, ensure_ascii=False),
            db_path=self.db_path,
        )
        # tri-vault 可选镜像：MASE_MEMORY_LAYOUT=tri 时，同一写入会反映为
        # <vault>/sessions/<row_id>.json，方便用户 git diff 记忆桶。否则 no-op，
        # SQLite 仍是召回的唯一事实源。
        if _tri_vault is not None and _tri_vault.is_enabled():
            try:
                _tri_vault.write_bucket(
                    "sessions",
                    f"{thread_id or 'default'}-{row_id}",
                    {
                        "thread_id": thread_id or "default",
                        "thread_label": thread_label or "",
                        "user_query": user_query or "",
                        "assistant_response": assistant_response or "",
                        "summary": summary or "",
                        "topic_tokens": topic_tokens or [],
                        "metadata": metadata or {},
                    },
                )
            except (OSError, ValueError) as exc:  # pragma: no cover — vault is best-effort mirror
                import logging
                logging.getLogger("mase.memory").warning(
                    "tri_vault_mirror_failed row_id=%s err=%s", row_id, exc,
                )
        return "ok"

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
    ) -> list[dict[str, Any]]:
        """执行 facts-first + FTS/BM25 + Python 重排的记忆搜索。"""
        del date_hint, top_k, semantic_query
        scope = dict(scope_filters or {})
        terms = self._extract_terms(keywords, full_query=full_query, query_variants=query_variants)
        if not terms:
            return []
        effective_limit = int(limit or 5)

        # facts-first：先查 entity_state，再触碰 memory_log 事件证据。
        entity_results = self._search_entity_state(terms, limit=effective_limit, scope_filters=scope)
        history_results: list[dict[str, Any]] = []
        if scope.get("include_history"):
            history_results = search_entity_fact_history_by_keyword(
                terms,
                limit=max(1, min(effective_limit, 3)),
                db_path=self.db_path,
                tenant_id=scope.get("tenant_id"),
                workspace_id=scope.get("workspace_id"),
                visibility=scope.get("visibility"),
            )

        primary_terms = sorted({t for t in terms if len(t) >= 3}, key=len, reverse=True)[:8]
        # CJK 模糊正则：中文 token 长度 3-5 时，允许相邻字之间最多插入 1 字。
        # 可捕捉“物理学”匹配“物理理学”等形态变体；规则泛化到任意 CJK 单字插入，
        # 不使用 benchmark 专用 token。
        fuzzy_patterns: dict[str, Any] = {}
        for t in terms:
            if len(t) >= 3 and len(t) <= 5 and all('\u4e00' <= c <= '\u9fff' for c in t):
                literal = re.escape(t)
                fuzzy = ".{0,1}".join(re.escape(c) for c in t)
                if fuzzy != literal:
                    try:
                        fuzzy_patterns[t] = re.compile(fuzzy)
                    except re.error:
                        pass
        candidate_ids: set[int] = set()
        if getattr(self, "_fts_enabled", False):
            try:
                with self._connect() as conn:
                    fts_terms = []
                    for t in primary_terms or terms:
                        # FTS MATCH 语法对引号/通配符敏感，先做最小清洗再拼 OR 查询。
                        cleaned = re.sub(r'["*()]', " ", t).strip()
                        if not cleaned:
                            continue
                        if " " in cleaned or any(ord(c) > 127 for c in cleaned):
                            fts_terms.append(f'"{cleaned}"')
                        else:
                            fts_terms.append(cleaned)
                    if fts_terms:
                        match_query = " OR ".join(fts_terms[:12])
                        rows = conn.execute(
                            "SELECT rowid FROM memory_fts WHERE memory_fts MATCH ? ORDER BY bm25(memory_fts) LIMIT ?",
                            (match_query, max(effective_limit * 6, 30)),
                        ).fetchall()
                        for r in rows:
                            candidate_ids.add(int(r[0]))
            except sqlite3.OperationalError:
                pass
        all_rows = fetch_memory_rows(
            db_path=self.db_path,
            chronological=False,
            include_superseded=False,
            tenant_id=scope.get("tenant_id"),
            workspace_id=scope.get("workspace_id"),
            visibility=scope.get("visibility"),
        )
        scored: list[dict[str, Any]] = []
        for row in all_rows:
            content = str(row.get("content") or "")
            haystack = " ".join([
                content,
                str(row.get("summary") or ""),
                str(row.get("thread_label") or ""),
                str(row.get("topic_tokens") or ""),
            ]).lower()
            if thread_hint and thread_hint.lower() not in haystack:
                continue
            distinct_hits = 0
            total_hits = 0
            primary_hits = 0
            for term in terms:
                lowered = term.lower()
                if not lowered:
                    continue
                count = haystack.count(lowered)
                if count == 0 and term in fuzzy_patterns:
                    fuzzy_count = len(fuzzy_patterns[term].findall(haystack))
                    if fuzzy_count > 0:
                        # 模糊命中视为真实命中，但多次命中仍被后续 min/score 限制折扣。
                        count = fuzzy_count
                if count > 0:
                    distinct_hits += 1
                    total_hits += count
                    if term in primary_terms:
                        primary_hits += min(count, 3)
            if distinct_hits == 0 and int(row.get("id") or 0) not in candidate_ids:
                continue
            cooccur_bonus = 0
            if primary_hits >= 2:
                cooccur_bonus = primary_hits * 2
            fts_bonus = 3 if int(row.get("id") or 0) in candidate_ids else 0
            score = distinct_hits * 2 + min(total_hits, 12) + cooccur_bonus + fts_bonus
            if score <= 0:
                continue
            row["score"] = score
            scored.append(row)
        scored.sort(key=lambda item: (-int(item.get("score") or 0), -int(item.get("id") or 0)))
        if scope.get("use_hybrid_rerank") and scored:
            from .hybrid_recall import HybridReranker

            scored = HybridReranker().rerank(full_query or " ".join(terms), scored)
        # 给日志结果补来源标记，entity_state 结果已经由底层 API 标注。
        for item in scored:
            item.setdefault("_source", "memory_log")
            item.setdefault("confidence", "medium")
            item.setdefault("retrieval_reason", "event_log_evidence")
        primary = entity_results[:effective_limit]
        remaining = max(0, effective_limit - len(primary))
        history_slice = history_results[:remaining]
        remaining -= len(history_slice)
        final = primary + history_slice + scored[:remaining]

        # event-log 语义候选发现(opt-in,MASE_EVENT_SEMANTIC_RECALL=1;诊断
        # lane,见 event_semantic_recall 模块 docstring)。只补关键词完全没
        # 命中的行,追加在词法结果之后——不重排、不占用、不替换任何词法槽位。
        if full_query:
            from .event_semantic_recall import discover_events, event_semantic_enabled

            if event_semantic_enabled():
                # 排除口径是"已经在返回结果里的行"，不是"关键词打过分的行"——
                # NoLiMa 式 needle 通常与问题共享锚点词（如人名），会在 scored
                # 里拿到一个非零但排不进 top-K 的分数；若按"打过分即排除"，
                # 语义发现永远补不到真正缺失的 top-K 位置，功能等于空转。
                already_seen = {int(item["id"]) for item in scored[:remaining] if item.get("id") is not None}
                discovered = discover_events(full_query, exclude_ids=already_seen, db_path=self.db_path)
                if discovered:
                    discovered_ids = {log_id for log_id, _sim in discovered}
                    by_id = {
                        int(row["id"]): row
                        for row in fetch_memory_rows(db_path=self.db_path, include_superseded=False)
                        if int(row["id"]) in discovered_ids
                    }
                    for log_id, similarity in discovered:
                        row = by_id.get(log_id)
                        if row is None:
                            continue
                        candidate = dict(row)
                        candidate["_source"] = "memory_log"
                        candidate["confidence"] = "low"
                        candidate["retrieval_reason"] = "event_semantic_discovery"
                        candidate["semantic_similarity"] = similarity
                        final.append(candidate)

        return final

    def build_fact_sheet(
        self,
        results: list[dict[str, Any]],
        question: str | None = None,
        evidence_thresholds: dict[str, Any] | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> str:
        """把搜索结果渲染为 executor 可读、审计可追溯的 fact-sheet。"""
        del question, evidence_thresholds, scope_filters
        if not results:
            return "无相关记忆。"
        lines: list[str] = []
        for index, item in enumerate(results, start=1):
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            source = item.get("_source", "memory_log")
            detail_bits: list[str] = []
            if source == "entity_state":
                # 当前实体事实携带状态、新鲜度、来源日志和可选证据片段。
                src_tag = "[FACT]"
                if item.get("conflict_status"):
                    detail_bits.append(f"state={item['conflict_status']}")
                if item.get("freshness"):
                    detail_bits.append(f"freshness={item['freshness']}")
                if item.get("history_depth"):
                    detail_bits.append(f"history={item['history_depth']}")
                if item.get("updated_at"):
                    detail_bits.append(f"updated={item['updated_at']}")
                if item.get("source_log_id") is not None:
                    detail_bits.append(f"src_log={item['source_log_id']}")
                if item.get("source_reason"):
                    detail_bits.append(f"reason={item['source_reason']}")
                evidence = str(item.get("source_content") or "").strip()
                if evidence:
                    detail_bits.append(f"evidence={evidence[:120]}")
            elif source == "entity_state_history":
                # 历史事实用于回答“之前/更正前是什么”，不能混同为当前值。
                src_tag = "[HIST]"
                if item.get("freshness"):
                    detail_bits.append(f"freshness={item['freshness']}")
                if item.get("supersede_reason"):
                    detail_bits.append(f"reason={item['supersede_reason']}")
                if item.get("superseded_at"):
                    detail_bits.append(f"ts={item['superseded_at']}")
                if item.get("source_log_id") is not None:
                    detail_bits.append(f"src_log={item['source_log_id']}")
            else:
                # 普通日志证据保留 thread 与时间信息，帮助 executor 解释来源。
                src_tag = "[LOG]"
                if item.get("thread_id"):
                    detail_bits.append(f"thread={item['thread_id']}")
                if item.get("freshness"):
                    detail_bits.append(f"freshness={item['freshness']}")
                timestamp = str(item.get("event_timestamp") or item.get("timestamp") or item.get("created_at") or "").strip()
                if timestamp:
                    detail_bits.append(f"ts={timestamp}")
            suffix = f" ({'; '.join(detail_bits)})" if detail_bits else ""
            lines.append(f"[{index}]{src_tag} {content}{suffix}")
        return "\n".join(lines) if lines else "无相关记忆。"

    def fetch_all_chronological(self, limit: int | None = None) -> list[dict[str, Any]]:
        """按 id 升序返回 memory_log 行，即时间正序。"""
        return fetch_memory_rows(db_path=self.db_path, limit=limit, chronological=True)

    def list_dates(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT substr(created_at, 1, 10) AS day FROM memory_log ORDER BY day DESC").fetchall()
        return [str(row["day"]) for row in rows if row["day"]]

    def fetch_recent_records(self, n: int = 5) -> list[dict[str, Any]]:
        return fetch_memory_rows(db_path=self.db_path, limit=max(1, int(n)))

    def fetch_records_by_topic(self, topic: str, limit: int | None = None) -> list[dict[str, Any]]:
        return self.search([topic], full_query=topic, limit=limit or 5, thread_hint=topic)


def get_notetaker(
    notetaker: BenchmarkNotetaker | None = None,
    *,
    config_path: str | Path | None = None,
    backend: str | None = None,  # reserved for future routing; currently unused
) -> BenchmarkNotetaker:
    """兼容工厂：优先返回注入的 notetaker，否则创建默认实例。

    集成层应统一使用这个入口，以便通过构造注入、环境变量
    ``MASE_BACKEND_CONFIG`` 或 ``config_path`` 替换后端，而无需引入第三套
    后端入口或改变既有调用面。

    优先级：
    1. ``notetaker`` 参数（测试或 DI 容器直接注入）
    2. ``config_path`` 参数
    3. ``MASE_BACKEND_CONFIG`` 环境变量（配置文件路径）
    4. 默认 ``BenchmarkNotetaker()``（既有行为）
    """
    import os

    if notetaker is not None:
        return notetaker

    effective_config = config_path
    if effective_config is None:
        env_cfg = os.environ.get("MASE_BACKEND_CONFIG")
        if env_cfg:
            effective_config = env_cfg

    return BenchmarkNotetaker(config_path=effective_config)


__all__ = ["BenchmarkNotetaker", "get_notetaker"]
