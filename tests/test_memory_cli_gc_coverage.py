from __future__ import annotations

import builtins
from typing import Any

import pytest

from mase import mase_cli
from mase_tools.memory import gc_agent


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int = 0) -> None:
        self.rows = rows or []
        self.rowcount = rowcount
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeCursor:
        self.statements.append((sql, params))
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False
        self.entered = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def __enter__(self) -> FakeConnection:
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_mase_cli_prints_and_filters_facts(monkeypatch, capsys) -> None:
    rows = [
        {
            "category": "project_status",
            "entity_key": "MASE",
            "entity_value": "coverage work",
            "updated_at": "2026-06-19",
        }
    ]
    cursor = FakeCursor(rows)
    conn = FakeConnection(cursor)
    monkeypatch.setattr(mase_cli, "get_connection", lambda: conn)

    mase_cli.print_menu()
    mase_cli.show_facts(category="project_status")

    out = capsys.readouterr().out
    assert "MASE Memory CLI" in out
    assert "coverage work" in out
    assert cursor.statements[-1][1] == ("project_status",)
    assert conn.closed is True


def test_mase_cli_empty_recent_logs_and_delete_paths(monkeypatch, capsys) -> None:
    empty_conn = FakeConnection(FakeCursor([]))
    monkeypatch.setattr(mase_cli, "get_connection", lambda: empty_conn)
    mase_cli.show_facts()
    mase_cli.show_recent_logs()
    assert "[Empty]" in capsys.readouterr().out

    deleted_cursor = FakeCursor(rowcount=1)
    deleted_conn = FakeConnection(deleted_cursor)
    monkeypatch.setattr(mase_cli, "get_connection", lambda: deleted_conn)
    answers = iter(["project_status", "MASE"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    mase_cli.delete_fact()
    assert deleted_cursor.statements[-1][1] == ("project_status", "MASE")
    assert "成功删除" in capsys.readouterr().out

    missing_cursor = FakeCursor(rowcount=0)
    monkeypatch.setattr(mase_cli, "get_connection", lambda: FakeConnection(missing_cursor))
    answers = iter(["project_status", "missing"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    mase_cli.delete_fact()
    assert "未找到匹配" in capsys.readouterr().out


def test_mase_cli_upsert_and_search_logs(monkeypatch, capsys) -> None:
    cursor = FakeCursor()
    monkeypatch.setattr(mase_cli, "get_connection", lambda: FakeConnection(cursor))
    answers = iter(["3", "release_gate", "green"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    mase_cli.upsert_fact()

    assert cursor.statements[-1][1] == ("project_status", "release_gate", "green")
    assert "成功将事实" in capsys.readouterr().out

    answers = iter([""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    mase_cli.search_logs()
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(
        "mase_tools.memory.db_core.search_event_log",
        lambda keywords, limit=10: [
            {"timestamp": "2026-06-19", "role": "user", "content": "Which relay is active?"}
        ],
    )
    answers = iter(["relay"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    mase_cli.search_logs()
    assert "Which relay is active" in capsys.readouterr().out


def test_mase_cli_main_dispatches_menu_choices(monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mase_cli, "show_facts", lambda category=None: calls.append(f"facts:{category}"))
    monkeypatch.setattr(mase_cli, "upsert_fact", lambda: calls.append("upsert"))
    monkeypatch.setattr(mase_cli, "delete_fact", lambda: calls.append("delete"))
    monkeypatch.setattr(mase_cli, "search_logs", lambda: calls.append("search"))
    monkeypatch.setattr(mase_cli, "show_recent_logs", lambda: calls.append("recent"))
    answers = iter(["1", "2", "project_status", "3", "4", "5", "6", "bad", "0"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    with pytest.raises(SystemExit) as exc:
        mase_cli.main()

    assert exc.value.code == 0
    assert calls == [
        "facts:None",
        "facts:project_status",
        "upsert",
        "delete",
        "search",
        "recent",
    ]
    assert "无效的选择" in capsys.readouterr().out


def test_gc_agent_no_logs_model_error_non_list_and_parse_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(gc_agent, "get_recent_logs", lambda limit: [])
    gc_agent.run_gc(limit=2)
    assert "No logs to process" in capsys.readouterr().out

    monkeypatch.setattr(gc_agent, "get_recent_logs", lambda limit: [{"timestamp": "t", "role": "user", "content": "c"}])

    class RaisingModel:
        def chat(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("model down")

    monkeypatch.setattr(gc_agent, "ModelInterface", RaisingModel)
    gc_agent.run_gc(limit=1)
    assert "Error calling LLM" in capsys.readouterr().out

    class DictModel:
        def chat(self, **kwargs: Any) -> dict[str, Any]:
            return {"message": {"content": '{"category": "general_facts"}'}}

    monkeypatch.setattr(gc_agent, "ModelInterface", DictModel)
    gc_agent.run_gc(limit=1)
    assert "LLM output is not a list" in capsys.readouterr().out

    class BadJsonModel:
        def chat(self, **kwargs: Any) -> dict[str, Any]:
            return {"message": {"content": "[not json]"}}

    monkeypatch.setattr(gc_agent, "ModelInterface", BadJsonModel)
    gc_agent.run_gc(limit=1)
    assert "Failed to parse JSON" in capsys.readouterr().out


def test_gc_agent_upserts_valid_facts_from_markdown_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        gc_agent,
        "get_recent_logs",
        lambda limit: [
            {"timestamp": "2026-06-19", "role": "user", "content": "I prefer concise audit reports."},
            {"timestamp": "2026-06-19", "role": "assistant", "content": "Noted."},
        ],
    )
    observed: dict[str, Any] = {}

    class CapturingModel:
        def chat(self, **kwargs: Any) -> dict[str, Any]:
            observed.update(kwargs)
            return {
                "message": {
                    "content": (
                        "```json\n"
                        "[{\"category\":\"user_preferences\",\"key\":\"report_style\",\"value\":\"concise\"},"
                        "{\"key\":\"empty_value\",\"value\":\"\"}]\n"
                        "```"
                    )
                }
            }

    upserts: list[tuple[str, str, str]] = []
    monkeypatch.setattr(gc_agent, "ModelInterface", CapturingModel)
    monkeypatch.setattr(gc_agent, "upsert_entity_fact", lambda category, key, value: upserts.append((category, key, value)))

    gc_agent.run_gc(limit=2)

    assert observed["agent_type"] == "executor"
    assert "user_preferences" in observed["override_system_prompt"]
    assert upserts == [("user_preferences", "report_style", "concise")]
    assert "Successfully processed 2 facts" in capsys.readouterr().out
