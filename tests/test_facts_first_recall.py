"""Focused tests for Phase-1 unified memory backend with facts-first default recall.

Covers:
1. BenchmarkNotetaker: entity_state facts appear before memory_log results in search().
2. BenchmarkNotetaker: build_fact_sheet shows [FACT]/[LOG] source markers.
3. db_core / api: facts_first_recall returns entity_state first, then event-log.
4. DB path unification: MASE_DB_PATH makes BN and db_core share the same file.
5. Schema cross-compat: db_core DB gains BN columns; BN DB gains db_core columns.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Ensure src/ is on sys.path for `from mase...` imports
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.benchmark_notetaker import BenchmarkNotetaker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bn(tmp_path: Path, monkeypatch) -> BenchmarkNotetaker:
    """Create an isolated BenchmarkNotetaker backed by a temp DB."""
    monkeypatch.delenv("MASE_DB_PATH", raising=False)
    monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
    bn = BenchmarkNotetaker()
    return bn


# ---------------------------------------------------------------------------
# 1. Entity facts appear BEFORE memory_log results
# ---------------------------------------------------------------------------

class TestFactsFirstOrdering:
    def test_entity_fact_precedes_log_entry(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        # Write a log entry about budget
        bn.write(
            user_query="What is my budget?",
            assistant_response="Your budget is $500.",
            summary="budget query",
            thread_id="t1",
        )
        # Upsert a current entity fact (newer, authoritative)
        with bn._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entity_state (category, entity_key, entity_value, updated_at) "
                "VALUES ('finance_budget', 'monthly_budget', '$1200', CURRENT_TIMESTAMP)"
            )
        results = bn.search(["budget"], full_query="budget")
        assert results, "search should return at least one result"
        sources = [r.get("_source") for r in results]
        # entity_state must appear before memory_log
        assert "entity_state" in sources, "entity_state result missing"
        first_entity = next(i for i, s in enumerate(sources) if s == "entity_state")
        first_log = next((i for i, s in enumerate(sources) if s == "memory_log"), len(sources))
        assert first_entity < first_log, (
            f"entity_state ({first_entity}) should come before memory_log ({first_log})"
        )

    def test_only_log_when_no_entity_match(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        bn.write(
            user_query="I love hiking.",
            assistant_response="Great hobby!",
            summary="hiking",
            thread_id="t1",
        )
        results = bn.search(["hiking"], full_query="hiking")
        sources = [r.get("_source") for r in results]
        assert all(s == "memory_log" for s in sources), (
            f"Expected only memory_log sources, got {sources}"
        )

    def test_empty_db_returns_empty(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        assert bn.search(["anything"]) == []

    def test_entity_result_has_content_field(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        with bn._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entity_state (category, entity_key, entity_value) "
                "VALUES ('user_preferences', 'language', 'Python')"
            )
        results = bn.search(["language", "Python"])
        entity_hits = [r for r in results if r.get("_source") == "entity_state"]
        assert entity_hits, "should have at least one entity_state hit"
        content = entity_hits[0]["content"]
        assert "Python" in content, f"content should include the value: {content!r}"
        assert "[FACT]" in content, f"content should have [FACT] prefix: {content!r}"


# ---------------------------------------------------------------------------
# 2. build_fact_sheet source markers
# ---------------------------------------------------------------------------

class TestBuildFactSheetSourceMarkers:
    def test_fact_tag_present(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        results = [
            {"content": "budget is $1200", "_source": "entity_state"},
            {"content": "User asked about budget", "_source": "memory_log"},
        ]
        sheet = bn.build_fact_sheet(results)
        assert "[FACT]" in sheet, f"[FACT] tag missing from:\n{sheet}"
        assert "[LOG]" in sheet, f"[LOG] tag missing from:\n{sheet}"

    def test_hist_tag_present(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        results = [{"content": "old budget was $500", "_source": "entity_state_history"}]
        sheet = bn.build_fact_sheet(results)
        assert "[HIST]" in sheet, f"[HIST] tag missing from:\n{sheet}"

    def test_no_source_defaults_to_log(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        results = [{"content": "some content"}]
        sheet = bn.build_fact_sheet(results)
        assert "[LOG]" in sheet, f"[LOG] default tag missing from:\n{sheet}"

    def test_empty_returns_no_memory(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        assert bn.build_fact_sheet([]) == "无相关记忆。"

    def test_fact_first_in_sheet(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        results = [
            {"content": "FACT_CONTENT", "_source": "entity_state"},
            {"content": "LOG_CONTENT", "_source": "memory_log"},
        ]
        sheet = bn.build_fact_sheet(results)
        assert sheet.index("[FACT]") < sheet.index("[LOG]"), (
            "[FACT] should appear before [LOG] in the fact sheet"
        )


# ---------------------------------------------------------------------------
# 3. db_core / api: facts_first_recall
# ---------------------------------------------------------------------------

class TestDbCoreFactsFirstRecall:
    def test_entity_facts_precede_log_in_recall(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "unified.db"))
        # Force schema re-init for fresh path
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "unified.db"))

        from mase_tools.memory.db_core import (  # noqa: PLC0415
            add_event_log,
            facts_first_recall,
            upsert_entity_fact,
        )

        add_event_log("t1", "user", "My old project budget was $300")
        upsert_entity_fact("finance_budget", "project_budget", "$900")

        results = facts_first_recall(["budget"], limit=5)
        assert results, "facts_first_recall should return results"
        sources = [r.get("_source") for r in results]
        assert "entity_state" in sources
        first_entity = next(i for i, s in enumerate(sources) if s == "entity_state")
        first_log = next((i for i, s in enumerate(sources) if s == "memory_log"), len(sources))
        assert first_entity < first_log, (
            f"entity_state at {first_entity} should precede memory_log at {first_log}"
        )

    def test_facts_first_recall_source_tags(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "unified2.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "unified2.db"))

        from mase_tools.memory.db_core import (  # noqa: PLC0415
            add_event_log,
            facts_first_recall,
            upsert_entity_fact,
        )
        add_event_log("t2", "user", "I like tennis")
        upsert_entity_fact("user_preferences", "sport", "tennis")

        results = facts_first_recall(["tennis"], limit=5)
        for r in results:
            assert "_source" in r, f"result missing _source: {r}"
            assert r["_source"] in ("entity_state", "memory_log"), (
                f"unexpected _source value: {r['_source']}"
            )

    def test_api_mase2_facts_first_recall(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "api_test.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "api_test.db"))

        from mase_tools.memory.api import mase2_facts_first_recall  # noqa: PLC0415
        from mase_tools.memory.db_core import add_event_log, upsert_entity_fact  # noqa: PLC0415

        add_event_log("t3", "user", "I study physics")
        upsert_entity_fact("user_preferences", "subject", "physics")

        results = mase2_facts_first_recall(["physics"], limit=5)
        assert results
        assert results[0]["_source"] == "entity_state", (
            f"first result should be entity_state, got: {results[0]['_source']!r}"
        )


# ---------------------------------------------------------------------------
# 4. DB path unification: MASE_DB_PATH makes BN and db_core use same file
# ---------------------------------------------------------------------------

class TestDbPathUnification:
    def test_bn_uses_mase_db_path(self, tmp_path, monkeypatch):
        unified = tmp_path / "shared.db"
        monkeypatch.setenv("MASE_DB_PATH", str(unified))
        from mase.benchmark_notetaker import BenchmarkNotetaker  # noqa: PLC0415
        bn = BenchmarkNotetaker()
        assert bn.db_path == unified.resolve(), (
            f"Expected {unified.resolve()}, got {bn.db_path}"
        )

    def test_bn_and_dbcore_share_facts_via_mase_db_path(self, tmp_path, monkeypatch):
        unified = tmp_path / "shared2.db"
        monkeypatch.setenv("MASE_DB_PATH", str(unified))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(unified))

        from mase.benchmark_notetaker import BenchmarkNotetaker  # noqa: PLC0415
        from mase_tools.memory.db_core import upsert_entity_fact  # noqa: PLC0415

        # Write a fact via db_core
        upsert_entity_fact("general_facts", "shared_key", "shared_value")

        # BN should see it via search (facts-first recall queries entity_state)
        bn = BenchmarkNotetaker()
        assert bn.db_path.resolve() == unified.resolve(), "BN must use the unified path"
        results = bn.search(["shared_value"], full_query="shared_value")
        entity_hits = [r for r in results if r.get("_source") == "entity_state"]
        assert entity_hits, (
            "BN.search should find the entity_state fact written by db_core on the shared DB"
        )

    def test_bn_falls_back_without_mase_db_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
        from mase.benchmark_notetaker import BenchmarkNotetaker  # noqa: PLC0415
        bn = BenchmarkNotetaker()
        assert bn.db_path.name == "benchmark_memory.sqlite3", (
            "Without MASE_DB_PATH, BN should use its own benchmark_memory.sqlite3"
        )


class TestScopeFilterCompatibility:
    def test_entity_search_ignores_unsupported_scope_filter_keys(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        with bn._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entity_state (category, entity_key, entity_value) "
                "VALUES ('project_status', 'server_port', '9909')"
            )

        results = bn.search(
            ["服务器端口"],
            full_query="服务器端口是多少？",
            scope_filters={"problem_type": "current_state_lookup", "visibility": "private"},
        )
        assert results
        assert results[0]["_source"] == "entity_state"
        assert "9909" in results[0]["content"]


# ---------------------------------------------------------------------------
# 5. Schema cross-compatibility
# ---------------------------------------------------------------------------

class TestSchemaCrossCompat:
    def test_dbcore_schema_has_bn_columns(self, tmp_path, monkeypatch):
        """When db_core creates the DB first, BN columns must be present."""
        db_file = tmp_path / "dbcore_first.db"
        monkeypatch.setenv("MASE_DB_PATH", str(db_file))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(db_file))
        db_core.init_db()

        conn = sqlite3.connect(str(db_file))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_log)").fetchall()}
        conn.close()
        for required in ("thread_label", "summary", "topic_tokens", "metadata", "created_at"):
            assert required in cols, (
                f"Column '{required}' missing from db_core-created memory_log (needed by BN)"
            )

    def test_bn_schema_has_dbcore_columns(self, tmp_path, monkeypatch):
        """When BN creates the DB first, db_core columns must be present."""
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
        from mase.benchmark_notetaker import BenchmarkNotetaker  # noqa: PLC0415
        bn = BenchmarkNotetaker()

        conn = sqlite3.connect(str(bn.db_path))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_log)").fetchall()}
        conn.close()
        for required in ("superseded_at", "superseded_by", "supersede_reason", "timestamp"):
            assert required in cols, (
                f"Column '{required}' missing from BN-created memory_log (needed by db_core)"
            )

    def test_bn_schema_has_entity_state_table(self, tmp_path, monkeypatch):
        """BN._init_db must create entity_state for facts-first recall."""
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
        from mase.benchmark_notetaker import BenchmarkNotetaker  # noqa: PLC0415
        bn = BenchmarkNotetaker()

        conn = sqlite3.connect(str(bn.db_path))
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "entity_state" in tables, (
            "BN._init_db should create entity_state table for facts-first recall"
        )

    def test_bn_write_succeeds_on_dbcore_db(self, tmp_path, monkeypatch):
        """BN.write() must not fail when the DB was initialised by db_core first."""
        db_file = tmp_path / "shared_write.db"
        monkeypatch.setenv("MASE_DB_PATH", str(db_file))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(db_file))
        db_core.init_db()

        from mase.benchmark_notetaker import BenchmarkNotetaker  # noqa: PLC0415
        bn = BenchmarkNotetaker()
        # This write must not raise despite BN columns being added via ALTER TABLE
        result = bn.write(
            user_query="test query",
            assistant_response="test answer",
            summary="test",
            thread_id="t_compat",
        )
        assert result == "ok"
