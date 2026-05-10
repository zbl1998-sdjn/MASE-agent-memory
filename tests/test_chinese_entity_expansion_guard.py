"""Regression tests for:
1. Chinese natural-language query expansion hitting machine-key entity facts.
2. Facts-first ordering remains intact after expansion.
3. Engine empty search_memory grounding guard.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

UTC = timezone.utc
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_bn(tmp_path: Path, monkeypatch):
    from mase.benchmark_notetaker import BenchmarkNotetaker
    monkeypatch.delenv("MASE_DB_PATH", raising=False)
    monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
    return BenchmarkNotetaker()


def _upsert(bn, category: str, key: str, value: str) -> None:
    with bn._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO entity_state (category, entity_key, entity_value, updated_at)"
            " VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (category, key, value),
        )


# ---------------------------------------------------------------------------
# 1. _expand_entity_search_terms unit tests
# ---------------------------------------------------------------------------

class TestExpandEntitySearchTerms:
    def _expand(self, keywords):
        from mase_tools.memory.db_core import _expand_entity_search_terms
        return _expand_entity_search_terms(keywords)

    def test_underscore_split(self):
        result = self._expand(["server_port"])
        low = [t.lower() for t in result]
        assert "server" in low, f"'server' missing from {result}"
        assert "port" in low, f"'port' missing from {result}"

    def test_hyphen_split(self):
        result = self._expand(["server-port"])
        low = [t.lower() for t in result]
        assert "server" in low
        assert "port" in low

    def test_chinese_server_expands_to_server(self):
        result = self._expand(["服务器"])
        low = [t.lower() for t in result]
        assert "server" in low, f"'server' alias missing from {result}"

    def test_chinese_port_expands_to_port(self):
        result = self._expand(["端口"])
        low = [t.lower() for t in result]
        assert "port" in low, f"'port' alias missing from {result}"

    def test_chinese_phrase_expands_both(self):
        # "服务器端口" should yield both server and port aliases
        result = self._expand(["服务器端口"])
        low = [t.lower() for t in result]
        assert "server" in low, f"'server' missing from {result}"
        assert "port" in low, f"'port' missing from {result}"

    def test_bounded_output(self):
        # Output should never exceed max_terms
        from mase_tools.memory.db_core import _expand_entity_search_terms
        result = _expand_entity_search_terms(["server_port"] * 50, max_terms=20)
        assert len(result) <= 20

    def test_deduplication(self):
        result = self._expand(["port", "port", "port"])
        low = [t.lower() for t in result]
        assert low.count("port") == 1, "duplicates should be removed"

    def test_passthrough_english(self):
        result = self._expand(["server"])
        low = [t.lower() for t in result]
        assert "server" in low


# ---------------------------------------------------------------------------
# 2. search_entity_facts_by_keyword: Chinese query hits stored server_port
# ---------------------------------------------------------------------------

class TestChineseQueryHitsEntityFact:
    def test_chinese_server_port_query_hits_stored_fact(self, tmp_path, monkeypatch):
        """Core regression: 服务器端口是多少？ should retrieve server_port=9909."""
        bn = _make_bn(tmp_path, monkeypatch)
        _upsert(bn, "project_status", "server_port", "9909")

        from mase_tools.memory.db_core import search_entity_facts_by_keyword
        # Simulate the terms a Chinese natural query would produce after _extract_terms
        results = search_entity_facts_by_keyword(
            ["服务器端口"],
            limit=5,
            db_path=bn.db_path,
        )
        assert results, "should find server_port fact via Chinese query 服务器端口"
        keys = [r.get("entity_key") for r in results]
        assert "server_port" in keys, f"server_port not found, got keys={keys}"
        values = [r.get("entity_value") for r in results]
        assert "9909" in values, f"value 9909 not found, got values={values}"

    def test_bn_search_chinese_retrieves_server_port(self, tmp_path, monkeypatch):
        """BenchmarkNotetaker.search with Chinese query retrieves server_port entity."""
        bn = _make_bn(tmp_path, monkeypatch)
        _upsert(bn, "project_status", "server_port", "9909")

        results = bn.search(["服务器端口是多少"], full_query="服务器端口是多少？")
        entity_hits = [r for r in results if r.get("_source") == "entity_state"]
        assert entity_hits, (
            "BenchmarkNotetaker.search should return entity_state hit via Chinese query"
        )
        content = entity_hits[0].get("content", "")
        assert "9909" in content, f"Expected 9909 in content, got: {content!r}"

    def test_direct_server_query_still_works(self, tmp_path, monkeypatch):
        """Plain English 'server port' query also retrieves server_port."""
        bn = _make_bn(tmp_path, monkeypatch)
        _upsert(bn, "project_status", "server_port", "9909")

        from mase_tools.memory.db_core import search_entity_facts_by_keyword
        results = search_entity_facts_by_keyword(["server_port"], limit=5, db_path=bn.db_path)
        assert results, "server_port direct query should hit"
        assert results[0]["entity_value"] == "9909"

    def test_numeric_value_lookup_hits_server_port(self, tmp_path, monkeypatch):
        """Value-only numeric lookup should still retrieve server_port=9909."""
        bn = _make_bn(tmp_path, monkeypatch)
        _upsert(bn, "project_status", "server_port", "9909")

        from mase_tools.memory.db_core import search_entity_facts_by_keyword

        results = search_entity_facts_by_keyword(["9909"], limit=5, db_path=bn.db_path)
        assert results, "numeric entity_value lookup should return at least one fact"
        assert all(r.get("entity_value") == "9909" or r.get("_source") != "entity_state" for r in results)
        assert any(
            r.get("entity_key") == "server_port" and r.get("entity_value") == "9909"
            for r in results
        ), f"server_port=9909 missing from results: {results!r}"

    def test_tz_aware_updated_at_returns_freshness(self, tmp_path, monkeypatch):
        """TZ-aware updated_at should not crash recall and should expose freshness."""
        bn = _make_bn(tmp_path, monkeypatch)
        aware_now = datetime.now(UTC).isoformat()
        with bn._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entity_state (category, entity_key, entity_value, updated_at) "
                "VALUES (?, ?, ?, ?)",
                ("project_status", "server_port", "9909", aware_now),
            )

        from mase_tools.memory.db_core import search_entity_facts_by_keyword

        results = search_entity_facts_by_keyword(["9909"], limit=5, db_path=bn.db_path)
        assert results, "tz-aware entity row should be searchable"
        hit = next(
            (r for r in results if r.get("entity_key") == "server_port" and r.get("entity_value") == "9909"),
            None,
        )
        assert hit is not None, f"server_port=9909 missing from results: {results!r}"
        assert hit.get("freshness") in {"fresh", "recent", "aging", "stale", "unknown"}

    def test_entity_results_expose_compatible_id_field(self, tmp_path, monkeypatch):
        """entity_state results may expose id=None for compatibility."""
        bn = _make_bn(tmp_path, monkeypatch)
        _upsert(bn, "project_status", "server_port", "9909")

        from mase_tools.memory.db_core import search_entity_facts_by_keyword

        results = search_entity_facts_by_keyword(["server_port"], limit=5, db_path=bn.db_path)
        assert results, "server_port query should hit"
        hit = next(r for r in results if r.get("entity_key") == "server_port")
        assert "id" in hit, f"id field missing from entity result: {hit!r}"
        assert hit["id"] is None

    def test_server_port_ranked_above_server_host_for_chinese_query(self, tmp_path, monkeypatch):
        """Ranking regression: server_port must beat newer server_host for query 服务器端口.

        This guards against the pure updated_at DESC ordering bug where a more
        recently inserted but less relevant row (server_host) displaced the
        correct answer (server_port).
        """
        import time
        bn = _make_bn(tmp_path, monkeypatch)

        # Insert server_port first (older)
        _upsert(bn, "project_status", "server_port", "9909")
        time.sleep(0.05)
        # Insert server_host second (newer) — pure recency would rank it first
        _upsert(bn, "project_status", "server_host", "192.168.1.1")

        from mase_tools.memory.db_core import search_entity_facts_by_keyword
        results = search_entity_facts_by_keyword(
            ["服务器端口"],
            limit=5,
            db_path=bn.db_path,
        )
        assert results, "should find at least one fact"
        keys = [r["entity_key"] for r in results]
        assert "server_port" in keys, f"server_port missing from results: {keys}"
        assert "server_host" in keys, f"server_host missing from results: {keys}"
        port_rank = keys.index("server_port")
        host_rank = keys.index("server_host")
        assert port_rank < host_rank, (
            f"server_port (rank {port_rank}) should rank above server_host (rank {host_rank}) "
            f"for query 服务器端口, even though server_host is newer. keys={keys}"
        )


# ---------------------------------------------------------------------------
# 3. Facts-first ordering intact after expansion
# ---------------------------------------------------------------------------

class TestFactsFirstOrderingWithExpansion:
    def test_entity_before_log_after_expansion(self, tmp_path, monkeypatch):
        """Facts-first ordering must hold even when query expansion is active."""
        bn = _make_bn(tmp_path, monkeypatch)
        bn.write(
            user_query="服务器端口是多少？",
            assistant_response="端口是9909。",
            summary="server port query",
            thread_id="t1",
        )
        _upsert(bn, "project_status", "server_port", "9909")

        results = bn.search(["服务器端口"], full_query="服务器端口是多少？")
        assert results, "search should return results"
        sources = [r.get("_source") for r in results]
        assert "entity_state" in sources, "entity_state result missing"
        first_entity = next(i for i, s in enumerate(sources) if s == "entity_state")
        first_log = next((i for i, s in enumerate(sources) if s == "memory_log"), len(sources))
        assert first_entity < first_log, (
            f"entity_state ({first_entity}) should precede memory_log ({first_log})"
        )

    def test_entity_result_content_has_fact_prefix(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        _upsert(bn, "project_status", "server_port", "9909")

        results = bn.search(["服务器端口"])
        entity_hits = [r for r in results if r.get("_source") == "entity_state"]
        assert entity_hits
        assert "[FACT]" in entity_hits[0]["content"]


# ---------------------------------------------------------------------------
# 4. Engine empty search_memory grounding guard
# ---------------------------------------------------------------------------

class TestEngineEmptySearchGuard:
    def _make_engine_with_mock_notetaker(self):
        """Build a minimal MASESystem with mocked dependencies."""
        from mase.engine import MASESystem

        mock_notetaker = MagicMock()
        mock_notetaker.build_fact_sheet.return_value = "无相关记忆。"

        mock_model = MagicMock()
        mock_router = MagicMock()
        mock_router.route.return_value = {"action": "search_memory", "keywords": ["test"]}
        mock_planner = MagicMock()
        mock_planner.plan.return_value = "Plan: answer grounded."

        engine = MASESystem.__new__(MASESystem)
        engine.notetaker_agent = mock_notetaker
        engine.model_interface = mock_model
        engine.router_agent = mock_router
        engine.planner_agent = mock_planner
        return engine

    def test_empty_results_returns_guard_text(self):
        engine = self._make_engine_with_mock_notetaker()
        fact_sheet, mode = engine._build_fact_sheet_with_notetaker(
            user_question="服务器端口是多少？",
            search_results=[],
            memory_heat="low",
        )
        assert mode == "none"
        assert fact_sheet != "无相关记忆。", (
            "empty search should NOT return '无相关记忆。' to avoid general_answer_reasoning fallback"
        )
        assert "猜测" in fact_sheet or "evidence" in fact_sheet.lower() or "未找到" in fact_sheet, (
            f"guard text should contain grounding instruction, got: {fact_sheet!r}"
        )

    def test_guard_text_prevents_general_answer_mode(self):
        """The guard text must NOT trigger general_answer_reasoning in select_executor_mode."""
        from mase.mode_selector import select_executor_mode

        engine = self._make_engine_with_mock_notetaker()
        fact_sheet, _mode = engine._build_fact_sheet_with_notetaker(
            user_question="服务器端口是多少？",
            search_results=[],
            memory_heat="low",
        )
        executor_mode = select_executor_mode("服务器端口是多少？", fact_sheet)
        assert executor_mode != "general_answer_reasoning", (
            f"Guard text should prevent general_answer_reasoning, got: {executor_mode!r}"
        )

    def test_non_empty_results_returns_normal_fact_sheet(self):
        """When search_results is non-empty, normal notetaker path is taken."""
        from mase.engine import MASESystem

        mock_notetaker = MagicMock()
        mock_notetaker.build_fact_sheet.return_value = "[1][FACT] project_status.server_port: 9909"

        mock_model = MagicMock()
        mock_model.chat.return_value = {"message": {"content": "port is 9909\nevidence_confidence=high\nverifier_action=answer"}}

        engine = MASESystem.__new__(MASESystem)
        engine.notetaker_agent = mock_notetaker
        engine.model_interface = mock_model
        engine.router_agent = MagicMock()
        engine.planner_agent = MagicMock()

        search_results = [{"content": "[FACT] project_status.server_port: 9909", "_source": "entity_state"}]
        fact_sheet, mode = engine._build_fact_sheet_with_notetaker(
            user_question="服务器端口是多少？",
            search_results=search_results,
            memory_heat="low",
        )
        # With non-empty results the fact sheet should contain actual content
        assert fact_sheet
        assert fact_sheet != "未找到相关记忆证据；不要猜测具体值。"
