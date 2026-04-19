"""SQLite-backed `BenchmarkNotetaker` used by the benchmark runner.

Two-stage retrieval: FTS5 BM25 candidate gathering + Python-side
co-occurrence/density rerank with substring fallback so recall stays high
even when FTS misses a partial / fuzzy term.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .utils import memory_root

try:
    from mase_tools.memory import tri_vault as _tri_vault  # opt-in mirror
except ImportError:  # pragma: no cover — package layout fallback
    _tri_vault = None  # type: ignore[assignment]


class BenchmarkNotetaker:
    """Simple per-run SQLite-backed memory used by the benchmark runner."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.db_path = memory_root(config_path) / "benchmark_memory.sqlite3"
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a SQLite connection with WAL pragmas, transaction wrapping,
        and guaranteed close on exit.

        Replaces the prior shape that returned a Connection used in
        ``with self._connect() as conn:`` blocks. Python's ``sqlite3``
        ``with conn:`` is a *transaction* context — it commits/rolls back but
        does NOT call ``close()``. On long-running benchmark runs that meant
        every ``write()``/``search()``/``_init_db()`` leaked a file handle
        until process exit, eventually starving Windows ``OSError [Errno 24]``.

        With this contextmanager every call site closes deterministically AND
        keeps the auto-commit/rollback semantics it relied on, with no
        callsite changes required (the ``with self._connect() as conn:``
        idiom continues to work).
        """
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT,
                    thread_label TEXT,
                    role TEXT,
                    content TEXT NOT NULL,
                    summary TEXT,
                    topic_tokens TEXT,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, summary, thread_label, tokenize='unicode61')"
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS memory_log_ai AFTER INSERT ON memory_log BEGIN
                        INSERT INTO memory_fts(rowid, content, summary, thread_label)
                        VALUES (new.id, COALESCE(new.content,''), COALESCE(new.summary,''), COALESCE(new.thread_label,''));
                    END;
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS memory_log_ad AFTER DELETE ON memory_log BEGIN
                        DELETE FROM memory_fts WHERE rowid = old.id;
                    END;
                    """
                )
                self._fts_enabled = True
            except sqlite3.OperationalError:
                self._fts_enabled = False
            conn.commit()

    def _extract_terms(self, keywords: list[str], full_query: str | None = None, query_variants: list[str] | None = None) -> list[str]:
        raw_terms = [str(item or "").strip() for item in [*(keywords or []), *(query_variants or [])] if str(item or "").strip()]
        if "__FULL_QUERY__" in raw_terms:
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
            # Lightweight English stem prefixes so "physics" matches "physicist",
            # "scientist" matches "scientists/scientific", "modern" matches "modernity", etc.
            # Strip 2-3 trailing chars for content words; conservative threshold to
            # avoid overgeneration on conversational text (LME regression observed
            # when threshold was 6 → common words like "today/yesterday/thinking/remember"
            # over-expanded and ranked irrelevant turns above the relevant ones).
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
        content_parts = [
            f"User: {user_query.strip()}" if str(user_query or "").strip() else "",
            f"Assistant: {assistant_response.strip()}" if str(assistant_response or "").strip() else "",
        ]
        if summary.strip():
            content_parts.append(f"Summary: {summary.strip()}")
        if key_entities:
            content_parts.append("Entities: " + ", ".join(str(item) for item in key_entities if str(item).strip()))
        content = "\n".join(part for part in content_parts if part)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_log (thread_id, thread_label, role, content, summary, topic_tokens, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id or "default",
                    thread_label or "",
                    "assistant" if str(assistant_response or "").strip() else "user",
                    content or str(user_query or "").strip(),
                    summary or "",
                    json.dumps(topic_tokens or [], ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            row_id = cursor.lastrowid
        # Tri-vault opt-in mirror: when MASE_MEMORY_LAYOUT=tri the same write
        # is reflected as a JSON file under <vault>/sessions/<row_id>.json,
        # so users can `git diff` the memory bucket. No-op otherwise — keeps
        # the SQLite path the single source of truth for retrieval.
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
        del date_hint, top_k, semantic_query, scope_filters
        terms = self._extract_terms(keywords, full_query=full_query, query_variants=query_variants)
        if not terms:
            return []
        effective_limit = int(limit or 5)
        primary_terms = sorted({t for t in terms if len(t) >= 3}, key=len, reverse=True)[:8]
        # Fuzzy CJK regex: for Chinese tokens >=3 chars, build a pattern allowing
        # up to 1 char insertion between adjacent chars. Catches morphological
        # variants like "物理学" matching "物理理学" (1-char insertion). Generalizable
        # to any single-char insertion in CJK text. NO benchmark-specific tokens.
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
        with self._connect() as conn:
            all_rows = [dict(row) for row in conn.execute("SELECT * FROM memory_log ORDER BY id DESC").fetchall()]
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
                        # Treat fuzzy match as a real hit but with discount on multi-hits
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
        return scored[:effective_limit]

    def build_fact_sheet(
        self,
        results: list[dict[str, Any]],
        question: str | None = None,
        evidence_thresholds: dict[str, Any] | None = None,
        scope_filters: dict[str, Any] | None = None,
    ) -> str:
        del question, evidence_thresholds, scope_filters
        if not results:
            return "无相关记忆。"
        lines: list[str] = []
        for index, item in enumerate(results, start=1):
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"[{index}] {content}")
        return "\n".join(lines) if lines else "无相关记忆。"

    def fetch_all_chronological(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return every memory_log row ordered by ascending id (chronological)."""
        with self._connect() as conn:
            sql = "SELECT * FROM memory_log ORDER BY id ASC"
            params: tuple[Any, ...] = ()
            if limit is not None:
                sql += " LIMIT ?"
                params = (int(limit),)
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        return rows

    def list_dates(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT substr(created_at, 1, 10) AS day FROM memory_log ORDER BY day DESC").fetchall()
        return [str(row["day"]) for row in rows if row["day"]]

    def fetch_recent_records(self, n: int = 5) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM memory_log ORDER BY id DESC LIMIT ?", (max(1, int(n)),)).fetchall()
        return [dict(row) for row in rows]

    def fetch_records_by_topic(self, topic: str, limit: int | None = None) -> list[dict[str, Any]]:
        return self.search([topic], full_query=topic, limit=limit or 5, thread_hint=topic)


__all__ = ["BenchmarkNotetaker"]
