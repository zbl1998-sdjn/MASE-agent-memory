"""Focused regression tests for the second-pass targeted fixes.

Covers four concrete gaps:

Gap 1 – db_core default DB resolution is now unified:
  Without MASE_DB_PATH, db_core._active_db_path / get_connection must resolve
  the same path as BenchmarkNotetaker in all normal runtime + benchmark flows.
  Precedence: MASE_DB_PATH → MASE_MEMORY_DIR/benchmark_memory.sqlite3 →
  MASE_CONFIG_PATH sibling memory/benchmark_memory.sqlite3 → legacy fallback.

Gap 2 – api.mase2_search_memory now routes to facts_first_recall:
  The public default recall helper returns entity_state results before
  memory_log results and preserves backward-compatible (keywords, limit) signature.

Gap 3 – Entity fact search matches category + key + value:
  search_entity_facts_by_keyword and BN._search_entity_state both match
  against category LIKE '%kw%', so a query like ["project_status"] hits the
  correct entity even when the key and value strings do not contain that word.

Gap 4 – Tests for all of the above (this file).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_db_core(monkeypatch):
    """Re-import db_core so resolve_db_path() is called with current env."""
    import importlib
    import mase_tools.memory.db_core as _mod
    importlib.invalidate_caches()
    _mod._SCHEMA_READY.clear()
    return _mod


# ===========================================================================
# Gap 1: DB path resolution unification
# ===========================================================================

class TestDbCorePathResolution:
    """resolve_db_path must mirror BenchmarkNotetaker's path logic at call time."""

    def test_mase_memory_dir_used_when_no_mase_db_path(self, tmp_path, monkeypatch):
        """MASE_MEMORY_DIR alone (no MASE_DB_PATH) → benchmark_memory.sqlite3 in that dir."""
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
        from mase_tools.memory.db_core import resolve_db_path  # noqa: PLC0415

        resolved = resolve_db_path()
        assert resolved.parent == tmp_path.resolve(), (
            f"Expected parent {tmp_path.resolve()}, got {resolved.parent}"
        )
        assert resolved.name == "benchmark_memory.sqlite3", resolved.name

    def test_mase_config_path_sibling_used(self, tmp_path, monkeypatch):
        """MASE_CONFIG_PATH alone → config.parent/memory/benchmark_memory.sqlite3."""
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
        monkeypatch.delenv("MASE_RUNS_DIR", raising=False)
        fake_config = tmp_path / "config.json"
        fake_config.write_text("{}")
        monkeypatch.setenv("MASE_CONFIG_PATH", str(fake_config))
        from mase_tools.memory.db_core import resolve_db_path  # noqa: PLC0415

        resolved = resolve_db_path()
        assert resolved.parent == (tmp_path / "memory").resolve(), (
            f"Expected config sibling memory dir, got {resolved.parent}"
        )
        assert resolved.name == "benchmark_memory.sqlite3", resolved.name

    def test_mase_runs_dir_used_when_no_memory_or_db_override(self, tmp_path, monkeypatch):
        """MASE_RUNS_DIR redirects default memory DBs out of the repo root."""
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
        monkeypatch.delenv("MASE_CONFIG_PATH", raising=False)
        monkeypatch.setenv("MASE_RUNS_DIR", str(tmp_path / "runs"))
        from mase_tools.memory.db_core import resolve_db_path  # noqa: PLC0415

        resolved = resolve_db_path()
        assert resolved.parent == (tmp_path / "runs" / "memory").resolve()
        assert resolved.name == "benchmark_memory.sqlite3"

    def test_import_time_resolution_does_not_create_memory_dir(self, tmp_path, monkeypatch):
        """Module import should not mkdir the config-sibling memory dir."""
        import importlib
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415

        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
        fake_config = tmp_path / "config.json"
        fake_config.write_text("{}")
        monkeypatch.setenv("MASE_CONFIG_PATH", str(fake_config))

        memory_dir = tmp_path / "memory"
        assert not memory_dir.exists()

        importlib.reload(db_core)

        assert not memory_dir.exists()

    def test_mase_db_path_takes_highest_priority(self, tmp_path, monkeypatch):
        """MASE_DB_PATH must win over MASE_MEMORY_DIR."""
        explicit = tmp_path / "explicit.db"
        monkeypatch.setenv("MASE_DB_PATH", str(explicit))
        monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path / "other"))
        from mase_tools.memory.db_core import resolve_db_path  # noqa: PLC0415

        assert resolve_db_path() == explicit.resolve()

    def test_get_connection_respects_mase_memory_dir_after_import(self, tmp_path, monkeypatch):
        """get_connection() must evaluate MASE_MEMORY_DIR at call-time, not import-time."""
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415

        db_core._SCHEMA_READY.discard(str(tmp_path / "benchmark_memory.sqlite3"))
        conn = db_core.get_connection()
        db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
        conn.close()
        assert db_file.parent == tmp_path.resolve(), (
            f"Connection should point to MASE_MEMORY_DIR, got {db_file}"
        )

    def test_bn_and_dbcore_share_db_via_mase_memory_dir(self, tmp_path, monkeypatch):
        """Without MASE_DB_PATH, BN and db_core must use the same file via MASE_MEMORY_DIR."""
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        from mase.benchmark_notetaker import BenchmarkNotetaker  # noqa: PLC0415

        expected = (tmp_path / "benchmark_memory.sqlite3").resolve()
        db_core._SCHEMA_READY.discard(str(expected))

        bn = BenchmarkNotetaker()
        assert bn.db_path.resolve() == expected, f"BN path: {bn.db_path}"

        # Write a fact via db_core; BN.search must see it.
        db_core.upsert_entity_fact("general_facts", "shared_sentinel", "value_xyz")
        results = bn.search(["shared_sentinel"], full_query="shared_sentinel")
        entity_hits = [r for r in results if r.get("_source") == "entity_state"]
        assert entity_hits, (
            "BN.search should find the entity fact written by db_core on the shared DB"
        )


# ===========================================================================
# Gap 2: mase2_search_memory routes to facts_first_recall
# ===========================================================================

class TestMase2SearchMemoryFactsFirst:
    def test_returns_entity_state_before_memory_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "api_gap2.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "api_gap2.db"))

        from mase_tools.memory.db_core import add_event_log, upsert_entity_fact  # noqa: PLC0415
        from mase_tools.memory.api import mase2_search_memory  # noqa: PLC0415

        add_event_log("t1", "user", "The project budget is $300")
        upsert_entity_fact("finance_budget", "project_budget", "$1500")

        results = mase2_search_memory(["budget"], limit=5)
        assert results, "mase2_search_memory should return results"
        sources = [r.get("_source") for r in results]
        assert "entity_state" in sources, "entity_state result missing"
        first_entity = next(i for i, s in enumerate(sources) if s == "entity_state")
        first_log = next((i for i, s in enumerate(sources) if s == "memory_log"), len(sources))
        assert first_entity < first_log, (
            f"entity_state ({first_entity}) must come before memory_log ({first_log})"
        )

    def test_signature_backward_compatible(self, tmp_path, monkeypatch):
        """mase2_search_memory(keywords, limit) must still work and return list[dict]."""
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "api_compat.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "api_compat.db"))

        from mase_tools.memory.api import mase2_search_memory  # noqa: PLC0415
        from mase_tools.memory.db_core import add_event_log  # noqa: PLC0415

        add_event_log("t1", "user", "I went hiking last weekend")
        results = mase2_search_memory(["hiking"], 3)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, dict)

    def test_empty_keywords_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "api_empty.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "api_empty.db"))

        from mase_tools.memory.api import mase2_search_memory  # noqa: PLC0415

        assert mase2_search_memory([]) == []

    def test_no_entity_fact_falls_back_to_log(self, tmp_path, monkeypatch):
        """When no entity fact matches, mase2_search_memory still returns log entries."""
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "api_fallback.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "api_fallback.db"))

        from mase_tools.memory.db_core import add_event_log  # noqa: PLC0415
        from mase_tools.memory.api import mase2_search_memory  # noqa: PLC0415

        add_event_log("t1", "user", "I enjoy cycling on weekends")
        results = mase2_search_memory(["cycling"])
        log_hits = [r for r in results if r.get("_source") == "memory_log"]
        assert log_hits, "Should fall back to memory_log when no entity_state matches"


# ===========================================================================
# Gap 3: entity fact search matches category
# ===========================================================================

class TestEntityFactCategoryMatching:
    """search_entity_facts_by_keyword must match on category, not just key/value."""

    def test_category_match_in_dbcore(self, tmp_path, monkeypatch):
        """Searching for 'project_status' must hit a fact whose category='project_status'
        even when the key and value strings contain different words."""
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "cat_match.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "cat_match.db"))

        from mase_tools.memory.db_core import (  # noqa: PLC0415
            search_entity_facts_by_keyword,
            upsert_entity_fact,
        )

        # Key and value deliberately don't contain "project_status"
        upsert_entity_fact("project_status", "current_phase", "alpha release")

        results = search_entity_facts_by_keyword(["project_status"])
        assert results, "should match fact by category even when key/value differ"
        assert results[0].get("_source") == "entity_state"
        assert results[0].get("category") == "project_status"

    def test_category_match_via_bn_search(self, tmp_path, monkeypatch):
        """BN.search must also surface a fact matched only by its category name."""
        monkeypatch.delenv("MASE_DB_PATH", raising=False)
        monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
        from mase.benchmark_notetaker import BenchmarkNotetaker  # noqa: PLC0415

        bn = BenchmarkNotetaker()
        with bn._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entity_state "
                "(category, entity_key, entity_value, updated_at) "
                "VALUES ('project_status', 'deadline', '2025-Q3', CURRENT_TIMESTAMP)"
            )

        results = bn.search(["project_status"], full_query="project_status")
        entity_hits = [r for r in results if r.get("_source") == "entity_state"]
        assert entity_hits, (
            "BN.search should return the entity_state fact matched by category"
        )
        assert entity_hits[0]["category"] == "project_status"

    def test_all_three_columns_searchable(self, tmp_path, monkeypatch):
        """Verify category, entity_key, and entity_value are each independently searchable."""
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "three_col.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "three_col.db"))

        from mase_tools.memory.db_core import (  # noqa: PLC0415
            search_entity_facts_by_keyword,
            upsert_entity_fact,
        )

        upsert_entity_fact("finance_budget", "annual_limit", "50000_dollars")

        # Match by category
        assert search_entity_facts_by_keyword(["finance_budget"]), "category not matched"
        # Match by key
        assert search_entity_facts_by_keyword(["annual_limit"]), "entity_key not matched"
        # Match by value
        assert search_entity_facts_by_keyword(["50000_dollars"]), "entity_value not matched"

    def test_no_match_when_keyword_unrelated(self, tmp_path, monkeypatch):
        """Non-matching keyword should return empty even with category-aware search."""
        monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "no_match.db"))
        import mase_tools.memory.db_core as db_core  # noqa: PLC0415
        db_core._SCHEMA_READY.discard(str(tmp_path / "no_match.db"))

        from mase_tools.memory.db_core import (  # noqa: PLC0415
            search_entity_facts_by_keyword,
            upsert_entity_fact,
        )

        upsert_entity_fact("project_status", "phase", "beta")
        results = search_entity_facts_by_keyword(["completely_unrelated_keyword_xyz"])
        assert results == [], f"Expected no results, got {results}"
